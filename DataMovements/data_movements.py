import hashlib
import json
import time
from datetime import datetime

import mercantile
import networkx
import numpy as np
import pandas as pd
import shapely
from scipy.interpolate import CubicSpline
from sqlalchemy import and_, desc

from DataMovements.model import db, Hashes, Datasets, PositionsCleaned, Clusters, ClusterMembers, DatasetAnalysisLink, \
    ClAverageValues, ClPolygons, GraphVertexes, GraphEdges, Graphs, ApprovedGraphs


def fetch_datasets_for_user(user_id):
    all_datasets = db.session.query(Datasets.id, Datasets.dataset_name).order_by(Datasets.dataset_name).all()
    mine_datasets = db.session.query(Datasets.id, Datasets.dataset_name).filter_by(user_id=user_id).order_by(
        Datasets.dataset_name).all()

    all_list = [{'id': ds.id, 'name': ds.dataset_name} for ds in all_datasets]
    mine_list = [{'id': ds.id, 'name': ds.dataset_name} for ds in mine_datasets]

    return {'all': all_list, 'mine': mine_list}


def read_csv_or_xlsx(file):
    if file.filename.endswith('.csv'):
        return pd.read_csv(file, sep=';', decimal=',')
    elif file.filename.endswith('.xlsx'):
        return pd.read_excel(file)
    raise ValueError("Неподдерживаемый формат файла. Пожалуйста, используйте .csv или .xlsx")


def get_hash_value(hash_id):
    hash_obj = db.session.query(Hashes).filter_by(hash_id=hash_id).first()
    return hash_obj.hash_value


def get_ds_hash_id(dataset_id):
    dsal_obj = db.session.query(Datasets).filter_by(id=dataset_id).first()
    return dsal_obj.source_hash_id


def integrity_check(hash_value, dataset_name):
    hash_obj = db.session.query(Hashes).filter_by(hash_value=hash_value).first()
    if hash_obj and hash_obj.source_of_datasets:
        existing_dataset = hash_obj.source_of_datasets[0]
        return True, f'Датасет с таким содержимым был создан ранее: {existing_dataset.dataset_name}'

    dataset_obj = db.session.query(Datasets).filter_by(dataset_name=dataset_name).first()
    if dataset_obj:
        return False, 'Название датасета не уникально!'

    return None


def store_dataset(df: pd.DataFrame, dataset_name, user_id, hash_value):
    new_hash = Hashes(hash_value=hash_value, timestamp=datetime.now(), params=None)
    db.session.add(new_hash)
    db.session.flush()

    new_dataset = Datasets(dataset_name=dataset_name, user_id=user_id, source_hash_id=new_hash.hash_id)
    db.session.add(new_dataset)

    df['hash_id'] = new_hash.hash_id
    records = df.to_dict(orient='records')
    db.session.bulk_insert_mappings(PositionsCleaned, records)

    db.session.commit()


def haversine_distance(lon1, lat1, lon2, lat2):
    R = 6371
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c


def spline_interpolation(df: pd.DataFrame, max_gap_minutes: int) -> pd.DataFrame:
    df = df.sort_values('timestamp').reset_index(drop=True)
    if len(df) < 2:
        return df

    time_diffs = df['timestamp'].diff().dt.total_seconds() / 60
    df['gap_group'] = (time_diffs > max_gap_minutes).cumsum()

    final_segments = []
    for _, group in df.groupby('gap_group'):
        group = group.reset_index(drop=True)
        if len(group) < 2:
            final_segments.append(group)
            continue

        distances = [0]
        for i in range(1, len(group)):
            dist = haversine_distance(group.loc[i - 1, 'lon'], group.loc[i - 1, 'lat'], group.loc[i, 'lon'],
                                      group.loc[i, 'lat'])
            distances.append(distances[-1] + dist)
        group['distance'] = distances

        group_no_duplicates = group.drop_duplicates(subset='distance').reset_index(drop=True)
        if len(group_no_duplicates) < 2:
            final_segments.append(group)
            continue

        cs_lat = CubicSpline(group_no_duplicates['distance'], group_no_duplicates['lat'])
        cs_lon = CubicSpline(group_no_duplicates['distance'], group_no_duplicates['lon'])

        start_time = group['timestamp'].min()
        end_time = group['timestamp'].max()
        if start_time == end_time:
            final_segments.append(group)
            continue

        target_time_grid = pd.date_range(start=start_time, end=end_time, freq='1min')

        original_times_sec = (group_no_duplicates['timestamp'] - start_time).dt.total_seconds()
        target_times_sec = (target_time_grid - start_time).total_seconds()
        new_distances = np.interp(target_times_sec, original_times_sec, group_no_duplicates['distance'])

        new_lat = cs_lat(new_distances)
        new_lon = cs_lon(new_distances)
        new_speeds = np.interp(new_distances, group_no_duplicates['distance'], group_no_duplicates['speed'])

        course_rad = np.deg2rad(group_no_duplicates['course'])
        course_x = np.cos(course_rad)
        course_y = np.sin(course_rad)
        new_course_x = np.interp(new_distances, group_no_duplicates['distance'], course_x)
        new_course_y = np.interp(new_distances, group_no_duplicates['distance'], course_y)
        new_course_rad = np.arctan2(new_course_y, new_course_x)
        new_courses = np.rad2deg(new_course_rad) % 360

        interp_df = pd.DataFrame({
            'timestamp': target_time_grid,
            'lat': new_lat,
            'lon': new_lon,
            'speed': new_speeds,
            'course': new_courses,
            'id_marine': group['id_marine'].iloc[0]
        })

        combined_df = pd.concat([group.drop(columns=['gap_group', 'distance']), interp_df])
        combined_df = combined_df.sort_values('timestamp').drop_duplicates(subset='timestamp', keep='first')

        final_segments.append(combined_df)

    if not final_segments:
        return df

    return pd.concat(final_segments, ignore_index=True)


def linear_interpolation(df_data: pd.DataFrame, max_gap_minutes: int) -> pd.DataFrame:
    result = []
    for ship_id, group in df_data.groupby('id_marine'):
        full_time = pd.date_range(group['timestamp'].min(), group['timestamp'].max(), freq='1min')
        group = group.set_index('timestamp').reindex(full_time)
        group['id_marine'] = ship_id
        result.append(group)
    df_data = pd.concat(result)
    df_data.index.name = 'timestamp'
    df_data = df_data.sort_values(['id_marine', 'timestamp'])

    def interpolate_with_gap(g):
        orig = g[g[['lat', 'lon', 'speed', 'course']].notna().all(axis=1)]
        time_diff = orig.index.to_series().diff().dt.total_seconds() / 60
        group_id = (time_diff > max_gap_minutes).cumsum().reindex(g.index, method='ffill').fillna(0).astype(int)
        g['gap_group'] = group_id.values

        for col in ['lat', 'lon', 'speed']:
            for grp, sub_g in g.groupby('gap_group'):
                mask = sub_g[[col]].notna().any(axis=1)
                if mask.sum() >= 2:
                    g.loc[sub_g.index, col] = sub_g[col].interpolate(method='time')

        for grp, sub_g in g.groupby('gap_group'):
            mask = sub_g[['course']].notna().any(axis=1)
            if mask.sum() >= 2:
                sin_course = np.sin(np.deg2rad(sub_g['course']))
                cos_course = np.cos(np.deg2rad(sub_g['course']))
                sin_course_interp = sin_course.interpolate(method='time')
                cos_course_interp = cos_course.interpolate(method='time')
                course_interp = np.rad2deg(np.arctan2(sin_course_interp, cos_course_interp))
                course_interp = (course_interp + 360) % 360
                g.loc[sub_g.index, 'course'] = course_interp

        g = g.drop(['gap_group'], axis=1)
        return g

    df_data = df_data.groupby('id_marine').apply(interpolate_with_gap)
    return df_data


def process_and_store_dataset(df_data, df_marine, dataset_name, user_id, interpolation, algorithm,
                              max_gap_minutes: int = 30):
    try:
        df_data = read_csv_or_xlsx(df_data)
        df_marine = read_csv_or_xlsx(df_marine)
        if not {'id_marine', 'lat', 'lon', 'speed', 'course', 'date_add', 'age'}.issubset(
                set(df_data.columns.tolist())):
            raise Exception('проверяйте формат файла с данными о движении.')
        if not {'id_marine', 'port', 'length'}.issubset(set(df_marine.columns.tolist())):
            raise Exception('проверяйте формат файла с данными о судах.')

        if max_gap_minutes:
            max_gap_minutes = int(max_gap_minutes)

        hash_value = hashlib.md5(
            (df_data.to_csv() + df_marine.to_csv() + str(interpolation) + str(max_gap_minutes) + str(algorithm)).encode(
                'utf-8')).hexdigest()

        result_integrity_check = integrity_check(hash_value, dataset_name)
        if result_integrity_check is not None:
            return result_integrity_check

        df_data['timestamp'] = pd.to_datetime(df_data['date_add']) - pd.to_timedelta(df_data['age'], unit='m')
        df_data = pd.merge(df_data, df_marine[['id_marine', 'port', 'length']], how='left', on='id_marine').dropna(
            axis=0)
        df_data = df_data.loc[
            (df_data['course'] != 511) & (df_data['port'] != 0) & (df_data['length'] != 0)].reset_index(
            drop=True)
        df_data = df_data[['id_marine', 'lat', 'lon', 'speed', 'course', 'timestamp']]
        df_data = (
            df_data
            .drop_duplicates(subset=['id_marine', 'lat', 'lon', 'speed', 'course'], keep='first')
            .drop_duplicates(subset=['id_marine', 'timestamp'], keep='first')
            .dropna(axis=0)
        )
        df_data = df_data.sort_values(['id_marine', 'timestamp'])

        if interpolation:
            if algorithm == 'spline':
                df_data = (df_data.groupby('id_marine', group_keys=False).apply(
                    lambda g: spline_interpolation(g, max_gap_minutes)))
            elif algorithm == 'linear':
                df_data = linear_interpolation(df_data, max_gap_minutes)
            df_data = df_data.reset_index(drop=True)

        df_data = df_data[['lat', 'lon', 'speed', 'course']].dropna(axis=0).drop_duplicates()
        df_data = df_data.rename(columns={'lat': 'latitude', 'lon': 'longitude'})

        store_dataset(df_data, dataset_name, user_id, hash_value)

        return True, f'Создан датасет: {dataset_name}'

    except Exception as exc:
        db.session.rollback()
        error_message = exc.args[0] if exc.args else str(exc)
        return False, f'Ошибка при создании датасета: {error_message}'


def load_positions_cleaned(dataset_id):
    dataset = db.session.get(Datasets, int(dataset_id))
    if not dataset:
        raise ValueError("Датасет не найден.")

    return pd.read_sql(
        db.session.query(
            PositionsCleaned.position_id,
            PositionsCleaned.latitude.label('lat'),
            PositionsCleaned.longitude.label('lon'),
            PositionsCleaned.speed,
            PositionsCleaned.course
        ).filter_by(hash_id=dataset.source_hash_id).statement,
        db.engine
    )


def load_clusters(cl_hash_id):
    return cl_hash_id, pd.read_sql(
        db.session.query(
            Clusters.cluster_num.label('cluster'),
            PositionsCleaned.latitude.label('lat'),
            PositionsCleaned.longitude.label('lon'),
            PositionsCleaned.speed,
            PositionsCleaned.course
        )
        .join(ClusterMembers,
              (Clusters.hash_id == ClusterMembers.hash_id) &
              (Clusters.cluster_num == ClusterMembers.cluster_num))
        .join(PositionsCleaned, ClusterMembers.position_id == PositionsCleaned.position_id)
        .filter(Clusters.hash_id == cl_hash_id)
        .statement, db.engine)


def check_clusters(clustering_params: dict):
    params_for_hashing = {k: v for k, v in clustering_params.items() if k != 'hull_type'}
    params_str = json.dumps(params_for_hashing, sort_keys=True)
    hash_value = hashlib.md5(params_str.encode('utf-8')).hexdigest()

    hash_obj = db.session.query(Hashes).filter_by(hash_value=hash_value).first()

    if hash_obj:
        print(f"Найден существующий результат кластеризации с hash_id: {hash_obj.hash_id}")
        return load_clusters(hash_obj.hash_id)
    else:
        return None, None


def store_avg_values(df: pd.DataFrame, hash_id: int):
    avg_speeds = {}
    avg_courses = {}

    cluster_count = max(df['cluster']) + 1
    for cluster in range(cluster_count):
        cluster_data = df[df['cluster'] == cluster]
        speeds = cluster_data['speed'].dropna()
        courses = cluster_data['course'].dropna()

        avg_speed = speeds.mean() if not speeds.empty else None

        if not courses.empty:
            sin_vals = np.sin(np.deg2rad(courses))
            cos_vals = np.cos(np.deg2rad(courses))
            avg_angle = np.rad2deg(np.arctan2(sin_vals.mean(), cos_vals.mean())) % 360
        else:
            avg_angle = None

        avg_speeds[cluster] = avg_speed
        avg_courses[cluster] = avg_angle

    records = []
    for cluster_num in avg_speeds.keys():
        records.append({
            'hash_id': hash_id,
            'cluster_num': int(cluster_num),
            'average_speed': avg_speeds[cluster_num],
            'average_course': avg_courses[cluster_num]
        })

    if records:
        db.session.bulk_insert_mappings(ClAverageValues, records)
        db.session.commit()


def load_avg_values(cl_hash_id):
    return (db.session.query(ClAverageValues.cluster_num, ClAverageValues.average_course, ClAverageValues.average_speed)
            .filter(ClAverageValues.hash_id == cl_hash_id)
            .all())


def store_clusters(df_results: pd.DataFrame, clustering_params: dict):
    source_dataset_id = clustering_params['dataset_id']
    params_for_hashing = {k: v for k, v in clustering_params.items() if k != 'hull_type'}
    params_str = json.dumps(params_for_hashing, sort_keys=True)
    hash_value = hashlib.md5(params_str.encode('utf-8')).hexdigest()

    new_hash = Hashes(
        hash_value=hash_value,
        timestamp=datetime.now(),
        params=clustering_params
    )
    db.session.add(new_hash)
    db.session.flush()

    source_dataset = db.session.get(Datasets, source_dataset_id)
    if not source_dataset:
        raise ValueError("Исходный датасет не найден!")

    link = DatasetAnalysisLink(dataset=source_dataset, analysis_hash=new_hash)
    db.session.add(link)

    unique_clusters = df_results['cluster'].unique()
    cluster_records = [{'hash_id': new_hash.hash_id, 'cluster_num': int(num)} for num in unique_clusters]
    if cluster_records:
        db.session.bulk_insert_mappings(Clusters, cluster_records)

    member_records_df = df_results[['position_id', 'cluster']].copy()
    member_records_df['hash_id'] = new_hash.hash_id
    member_records_df = member_records_df.rename(columns={'cluster': 'cluster_num'})
    db.session.bulk_insert_mappings(ClusterMembers, member_records_df.to_dict(orient='records'))

    db.session.commit()
    return new_hash.hash_id


def store_polygon_geoms(polygon_geoms: dict, cl_hash_id: int):
    records = []
    for cluster_num, bounds in polygon_geoms.items():
        for x, y in bounds:
            records.append({
                'hash_id': cl_hash_id,
                'cluster_num': int(cluster_num),
                'x': x,
                'y': y
            })
    if records:
        db.session.bulk_insert_mappings(ClPolygons, records)
        db.session.commit()


def load_polygon_geoms(cl_hash_id: int):
    polygons = {}
    rows = db.session.query(ClPolygons).filter_by(hash_id=cl_hash_id).all()
    for row in rows:
        polygons.setdefault(row.cluster_num, []).append((row.x, row.y))
    return polygons


def delete_dataset_by_id(dataset_id, current_user_id):
    """
    Удаляет датасет и все связанные с ним данные, включая хэши
    исходных данных, кластеризации и графов.
    """
    try:
        dataset_to_delete = db.session.get(Datasets, int(dataset_id))

        if not dataset_to_delete:
            return False, 'Датасет не найден.'

        dataset_name = dataset_to_delete.dataset_name

        if dataset_to_delete.user_id != current_user_id:
            return False, f'Отказано в доступе: вы не являетесь владельцем датасета "{dataset_name}"'

        hashes_to_check_later = set()

        if dataset_to_delete.source_hash_id:
            hashes_to_check_later.add(dataset_to_delete.source_hash_id)

        for link in dataset_to_delete.analysis_links:
            if link.analysis_hash_id:
                hashes_to_check_later.add(link.analysis_hash_id)

            for graph in link.graphs:
                if graph.hash_id:
                    hashes_to_check_later.add(graph.hash_id)

        print(f"Постановка на удаление датасета: '{dataset_name}' (ID: {dataset_id})")
        db.session.delete(dataset_to_delete)

        db.session.commit()
        print(f"Датасет '{dataset_name}' и его дочерние записи успешно удалены.")

        if hashes_to_check_later:
            print(f"Проверка на осиротевшие хэши: {list(hashes_to_check_later)}")
            for hash_id_to_check in reversed(list(hashes_to_check_later)):
                is_used_elsewhere = db.session.query(
                    db.or_(
                        db.session.query(Datasets).filter_by(source_hash_id=hash_id_to_check).exists(),
                        db.session.query(DatasetAnalysisLink).filter_by(analysis_hash_id=hash_id_to_check).exists(),
                        db.session.query(Graphs).filter_by(hash_id=hash_id_to_check).exists()
                    )
                ).scalar()

                if not is_used_elsewhere:
                    print(f"Хэш {hash_id_to_check} больше не используется. Удаление...")
                    hash_to_delete = db.session.get(Hashes, hash_id_to_check)
                    if hash_to_delete:
                        db.session.delete(hash_to_delete)

            db.session.commit()
            print("Очистка осиротевших хэшей завершена.")

        return True, f'Датасет "{dataset_name}" и все связанные данные успешно удалены.'

    except Exception as e:
        db.session.rollback()
        print(f"Критическая ошибка при удалении датасета {dataset_id}: {e}")
        return False, 'Произошла ошибка на сервере при удалении датасета.'


def store_extent(geographic_extent, dataset_id):
    if not all([dataset_id, geographic_extent and len(geographic_extent) == 4]):
        print("Ошибка: Для сохранения extent необходимы ID датасета и список из 4 координат.")
        return

    dataset_to_update = db.session.query(Datasets).get(dataset_id)

    if dataset_to_update:
        dataset_to_update.extent_min_x = geographic_extent[0]
        dataset_to_update.extent_min_y = geographic_extent[1]
        dataset_to_update.extent_max_x = geographic_extent[2]
        dataset_to_update.extent_max_y = geographic_extent[3]
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Произошла ошибка при сохранении extent: {e}")
    else:
        print(f"Ошибка: Не удалось найти датасет с ID {dataset_id} в базе данных.")


def load_graph(hash_id, map_renderer):
    start = time.time()
    graph_db = db.session.query(Graphs).filter_by(hash_id=hash_id).first()
    graph_nx = networkx.DiGraph()

    vertex_map = {}
    for i, vertex in enumerate(graph_db.vertexes):
        point = shapely.Point(map_renderer.get_img_coords_from_lat_lon(vertex.latitude, vertex.longitude))
        graph_nx.add_node(point)
        vertex_map[vertex.vertex_id] = point

    for edge in graph_db.edges:
        start_point = vertex_map.get(edge.start_vertex_id)
        end_point = vertex_map.get(edge.end_vertex_id)

        if start_point and end_point:
            graph_nx.add_edge(
                start_point,
                end_point,
                edge_id=edge.edge_id,
                weight=edge.weight,
                color=json.loads(edge.color),
                angle_deviation=edge.angle_deviation,
                distance=edge.distance,
                speed=edge.speed
            )

    print(
        f"Граф ID: {graph_db.graph_id} успешно загружен из БД: {graph_nx.number_of_nodes()} вершин, {graph_nx.number_of_edges()} ребер.")
    print(f'Время загрузки графа: {round(time.time() - start, 2)} сек.')
    return graph_db.graph_id, graph_db.hash_id, graph_nx


def get_hash_value_from_graph_params(graph_params):
    params_for_hashing = {
        'points_inside': graph_params['points_inside'],
        'distance_delta': graph_params['distance_delta'],
        'angle_of_vision': graph_params['angle_of_vision'],
        'dataset_id': graph_params['dataset_id'],
        'cl_hash_id': graph_params['cl_hash_id'],
        'hull_type': graph_params['hull_type']
    }
    params_str = json.dumps(params_for_hashing, sort_keys=True)
    hash_value = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return hash_value


def check_graph(graph_params: dict, map_renderer):
    hash_value = get_hash_value_from_graph_params(graph_params)
    hash_obj = db.session.query(Hashes).filter_by(hash_value=hash_value).first()

    if hash_obj:
        print(f"Найден существующий граф с hash_id: {hash_obj.hash_id}")
        return load_graph(hash_obj.hash_id, map_renderer)
    else:
        return None, None, None


def store_graph(graph: networkx.DiGraph, dataset_id: int, analysis_hash_id: int, map_renderer):
    start = time.time()
    graph_params = dict(map_renderer.graph_params)
    hash_value = get_hash_value_from_graph_params(graph_params)

    del graph_params['search_algorithm']
    new_hash = Hashes(
        hash_value=hash_value,
        timestamp=datetime.now(),
        params=graph_params
    )
    db.session.add(new_hash)
    db.session.flush()

    link = db.session.query(DatasetAnalysisLink).filter_by(
        dataset_id=dataset_id,
        analysis_hash_id=analysis_hash_id
    ).first()

    if not link:
        print(
            f"ОШИБКА: Не найдена связь для dataset_id {dataset_id} и analysis_hash_id {analysis_hash_id}. "
            f"Граф не будет сохранен.")
        return

    graph_db = Graphs(
        hash_id=new_hash.hash_id,
        dataset_id=dataset_id,
        analysis_hash_id=analysis_hash_id
    )

    node_to_vertex_map = {}
    for node in graph.nodes():
        lat, lon = map_renderer.get_lat_lon_from_img_coords(node.x, node.y)

        vertex_db = GraphVertexes(latitude=lat, longitude=lon)
        graph_db.vertexes.append(vertex_db)
        node_to_vertex_map[node] = vertex_db

    for start_node, end_node, edge_data in graph.edges(data=True):
        start_vertex_db = node_to_vertex_map[start_node]
        end_vertex_db = node_to_vertex_map[end_node]

        edge_db = GraphEdges(
            start_vertex=start_vertex_db,
            end_vertex=end_vertex_db,
            distance=edge_data.get('distance'),
            speed=edge_data.get('speed'),
            weight=edge_data.get('weight'),
            color=str(edge_data.get('color')),
            angle_deviation=edge_data.get('angle_deviation')
        )
        graph_db.edges.append(edge_db)
    try:
        db.session.add(graph_db)
        db.session.commit()
        print(
            f"Граф ID: {graph_db.graph_id} для результата кластеризации с hash_id: {analysis_hash_id} успешно сохранен: "
            f"{len(graph_db.vertexes)} вершин и {len(graph_db.edges)} ребер.")
        print(f'Время сохранения графа: {round(time.time() - start, 2)} сек.')
        return graph_db.graph_id
    except Exception as e:
        db.session.rollback()
        print(f"ОШИБКА при сохранении графа в БД: {e}")


def get_hash_params(hash_id):
    hash_obj = db.session.query(Hashes).filter_by(hash_id=hash_id).first()
    return hash_obj.params


def update_graph_edges(hash_id: int, new_params: dict, graph_nx: networkx.DiGraph):
    start = time.time()
    try:
        hash_obj = db.session.get(Hashes, hash_id)
        if hash_obj:
            hash_obj.params = new_params
            db.session.flush()

        bulk_updates = []
        for _, _, data in graph_nx.edges(data=True):
            edge_id = data.get('edge_id')
            if edge_id is not None:
                bulk_updates.append({
                    'edge_id': edge_id,
                    'weight': data.get('weight')
                })

        if bulk_updates:
            db.session.bulk_update_mappings(GraphEdges, bulk_updates)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при обновлении весов рёбер для графа с hash_id {hash_id}: {e}")
    finally:
        print(f'Время обновления весов: {round(time.time() - start, 2)} сек.')


# Для малышей беспилотников, вроде работает
def find_approved_graphs(start_coords: tuple, end_coords: tuple):
    try:
        start_lat, start_lon = start_coords
        end_lat, end_lon = end_coords
        start_x, start_y = mercantile.xy(start_lon, start_lat)
        end_x, end_y = mercantile.xy(end_lon, end_lat)

        graphs_db = db.session.query(Graphs).join(
            ApprovedGraphs, ApprovedGraphs.graph_id == Graphs.graph_id
        ).join(
            Datasets, Datasets.id == Graphs.dataset_id
        ).join(
            Hashes, Hashes.hash_id == Graphs.hash_id
        ).filter(
            and_(
                Datasets.extent_min_x <= start_x, start_x <= Datasets.extent_max_x,
                Datasets.extent_min_y <= start_y, start_y <= Datasets.extent_max_y,
                Datasets.extent_min_x <= end_x, end_x <= Datasets.extent_max_x,
                Datasets.extent_min_y <= end_y, end_y <= Datasets.extent_max_y
            )
        ).order_by(
            desc(Hashes.timestamp)
        ).all()

        if not graphs_db:
            print("Совпадений не найдено. Точки не входят ни в одну утвержденную область.")
            return None

        results = []
        print(f"Найдены одобренные графы (ID: {[graph_db.graph_id for graph_db in graphs_db]}).")
        for graph_db in graphs_db:
            results.append({'graph_params': graph_db.hash.params,
                            'clustering_params': graph_db.dataset_analysis_link.analysis_hash.params,
                            'cl_hash_id': graph_db.dataset_analysis_link.analysis_hash_id,
                            'gr_hash_id': graph_db.hash_id})
        return results
    except Exception as e:
        print(f"Произошла ошибка при поиске и загрузке графа: {e}")
        return None
