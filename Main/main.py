import os
import pickle
import time

from joblib import parallel_backend
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
import hashlib
from DataMovements.data_movements import load_positions_cleaned, process_and_store_dataset, check_clusters, store_clusters, store_avg_values
from Map.map import MapBuilder


# from sklearn.neighbors import NearestNeighbors
# import numpy as np
# import matplotlib.pyplot as plt
# import statistics

def call_process_and_store_dataset(file_positions, file_marine, dataset_name, user_id, interpolation, max_gap_minutes):
    return process_and_store_dataset(file_positions, file_marine, dataset_name, user_id, interpolation, max_gap_minutes)


def clustering(clustering_params, create_new_empty_map=False):
    weight_distance = float(clustering_params['weight_distance'])
    weight_speed = float(clustering_params['weight_speed'])
    weight_course = float(clustering_params['weight_course'])
    eps = float(clustering_params['eps'])
    min_samples = int(clustering_params['min_samples'])
    metric_degree = float(clustering_params['metric_degree'])
    ds_hash_id = int(clustering_params['dataset_id'])

    clustering_params_for_hashing = {
        key: value for key, value in clustering_params.items() if key != 'hull_type'
    }

    cl_hash_id, result_df = check_clusters(clustering_params_for_hashing)

    if cl_hash_id is not None:
        df = result_df
        min_lat = df['lat'].min()
        min_lon = df['lon'].min()
        max_lat = df['lat'].max()
        max_lon = df['lon'].max()
        dbscan_time = 0

    else:
        df = load_positions_cleaned(ds_hash_id)

        min_lat = df['lat'].min()
        min_lon = df['lon'].min()
        max_lat = df['lat'].max()
        max_lon = df['lon'].max()

        dbscan_start_time = time.time()
        # Нормализуем данные, значительно увеличивает вычислительную эффективность
        scaler = StandardScaler()
        X = scaler.fit_transform(df[['lat', 'lon', 'speed', 'course']])
        # Распараллеливаем вычисления
        with parallel_backend('loky', n_jobs=-1):
            # Нашел более правильную реализацию метрики, вроде работает получше и побыстрее
            clusters = DBSCAN(eps=eps, min_samples=min_samples, metric='minkowski', p=metric_degree,
                              metric_params={'w': [weight_distance, weight_distance,
                                                   weight_speed, weight_course]}).fit_predict(X)
            # # Создание графика для подбора eps
            # neighbors = NearestNeighbors(n_neighbors=min_samples, metric='minkowski', p=metric_degree,
            #                              metric_params={'w': [weight_distance, weight_distance,
            #                                                   weight_speed, weight_course]}).fit(X)
            # distances, indexes = neighbors.kneighbors(X)
        dbscan_time = round(time.time() - dbscan_start_time, 3)

        df['cluster'] = clusters

        cl_hash_id = store_clusters(df, clustering_params_for_hashing)
        store_avg_values(df[['cluster', 'speed', 'course']], cl_hash_id)
        df = df.drop('position_id', axis=1)

    # # Создание графика для подбора eps
    # mean_distances = np.mean(distances, axis=1)
    # mean_distances = np.sort(mean_distances)
    # plt.figure(figsize=(12, 8))
    # plt.plot(mean_distances)
    # plt.yticks(np.arange(np.max(mean_distances), step=0.1))
    # plt.xlabel('Sorted distances over all pairs')
    # plt.ylabel(f'Mean distance over {min_samples} nearest neighbors')
    # file_path = f'./static/images/clustered/clustered_{file_name}_eps_for_min_samples_{min_samples}.png'
    # plt.savefig(file_path)

    # # Кластеризация шума с увеличенным eps и уменьшенным min_samples
    # df2 = df.where(df['cluster'] == -1).dropna(how='any')
    # X = scaler.fit_transform(df2[['lat', 'lon', 'speed', 'course']])
    # with parallel_backend('loky', n_jobs=-1):
    #     # Нашел более правильную реализацию метрики, вроде работает получше и побыстрее
    #     clusters = DBSCAN(eps=eps * 1.1, min_samples=min_samples, metric='minkowski', p=metric_degree,
    #                       metric_params={'w': [weight_distance, weight_distance,
    #                                            weight_speed, weight_course]}).fit_predict(X)
    # max_cluster_number = max(df['cluster'])
    # df2['cluster'] = [cluster + max_cluster_number if cluster != -1 else cluster for cluster in clusters]
    # df.update(df2)

    if (not os.path.exists(f'./static/images/clean/with_points_{ds_hash_id}.png') or
            not os.path.exists(f'./static/images/clean/{ds_hash_id}.png')):
        create_new_empty_map = True
    map_builder = MapBuilder(west=min_lat, south=min_lon, east=max_lat, north=max_lon, zoom=12, df=df,
                             clean_file_name=ds_hash_id, processed_file_name=cl_hash_id,
                             create_new_empty_map=create_new_empty_map, cl_hash_id=cl_hash_id)
    map_builder.clustering_params = clustering_params
    map_builder.dbscan_time = dbscan_time
    clustered_images = map_builder.create_clustered_map()

    # # Обнуляем несериализуемые pickle поля
    # map_builder.map_image = None
    # map_builder.context = None
    # # Сохраняем дамп объекта map_builder
    # with open('./Main/map_builder_dump.pickle', 'wb') as dump_file:
    #     pickle.dump(map_builder, dump_file, protocol=pickle.HIGHEST_PROTOCOL)

    return clustered_images


def call_clustering(clustering_params):
    # try:
    #     with open('./Main/map_builder_dump.pickle', 'rb') as load_file:
    #         map_builder_loaded = pickle.load(load_file)
    #
    #     if map_builder_loaded.clustering_params == clustering_params:
    #         result = map_builder_loaded.create_clustered_map()
    #     else:
    #         result = clustering(clustering_params)
    #
    # except FileNotFoundError or EOFError:
    #     result = clustering(clustering_params)

    result = clustering(clustering_params)
    return result


def call_find_path(graph_params, coords):
    try:
        with open('./Main/map_builder_dump.pickle', 'rb') as load_file:
            map_builder_loaded = pickle.load(load_file)

        if len(map_builder_loaded.graph_params.keys()) == 0:
            map_builder_loaded.graph_params = graph_params
            result = map_builder_loaded.find_path(coords['start_long'], coords['start_lat'], coords['end_long'],
                                                  coords['end_lat'], create_new_graph=True)
        elif map_builder_loaded.graph_params == graph_params:
            result = map_builder_loaded.find_path(coords['start_long'], coords['start_lat'], coords['end_long'],
                                                  coords['end_lat'], create_new_graph=False)
        elif map_builder_loaded.graph_params['distance_delta'] == graph_params['distance_delta'] and \
                map_builder_loaded.graph_params['angle_of_vision'] == graph_params['angle_of_vision'] and \
                map_builder_loaded.graph_params['points_inside'] == graph_params['points_inside'] and \
                (map_builder_loaded.graph_params['weight_time_graph'] != graph_params['weight_time_graph'] or
                 map_builder_loaded.graph_params['weight_course_graph'] != graph_params['weight_course_graph'] or
                 map_builder_loaded.graph_params['weight_func_degree'] != graph_params['weight_func_degree'] or
                 map_builder_loaded.graph_params['search_algorithm'] != graph_params['search_algorithm']):
            # Пересчет ребер происходит очень быстро,
            # нет смысла отдельно обрабатывать случай, когда изменился только алгоритм поиска
            map_builder_loaded.graph_params = graph_params
            map_builder_loaded.recalculate_edges()
            result = map_builder_loaded.find_path(coords['start_long'], coords['start_lat'], coords['end_long'],
                                                  coords['end_lat'], create_new_graph=False)
        else:
            map_builder_loaded.graph_params = graph_params
            result = map_builder_loaded.find_path(coords['start_long'], coords['start_lat'], coords['end_long'],
                                                  coords['end_lat'], create_new_graph=True)
        # print(map_builder_loaded.graph)

    except FileNotFoundError or EOFError:
        clustering_params = {'weight_distance': 1.0, 'weight_speed': 5.0, 'weight_course': 20.0, 'eps': 0.309,
                             'min_samples': 50, 'metric_degree': 2.0, 'hull_type': 'convex_hull'}
        clustering(clustering_params)
        with open('./Main/map_builder_dump.pickle', 'rb') as load_file:
            map_builder_loaded = pickle.load(load_file)

        map_builder_loaded.graph_params = graph_params
        result = map_builder_loaded.find_path(coords['start_long'], coords['start_lat'], coords['end_long'],
                                              coords['end_lat'], create_new_graph=True)
        # print(map_builder_loaded.graph)

    # Обнуляем несериализуемые pickle поля
    map_builder_loaded.map_image = None
    map_builder_loaded.context = None
    # Сохраняем дамп объекта map_builder
    with open('./Main/map_builder_dump.pickle', 'wb') as dump_file:
        pickle.dump(map_builder_loaded, dump_file, protocol=pickle.HIGHEST_PROTOCOL)
    return result


def load_clustering_params():
    try:
        with open('./Main/map_builder_dump.pickle', 'rb') as load_file:
            map_builder_loaded = pickle.load(load_file)
            clustering_params = map_builder_loaded.clustering_params
            if len(clustering_params) == 0:
                clustering_params = {'weight_distance': 1.0, 'weight_speed': 5.0, 'weight_course': 20.0, 'eps': 0.309,
                                     'min_samples': 50, 'metric_degree': 2.0, 'hull_type': 'convex_hull'}
    except FileNotFoundError or EOFError:
        clustering_params = {'weight_distance': 1.0, 'weight_speed': 5.0, 'weight_course': 20.0, 'eps': 0.309,
                             'min_samples': 50, 'metric_degree': 2.0, 'hull_type': 'convex_hull'}
    return clustering_params


def load_graph_params():
    try:
        with open('./Main/map_builder_dump.pickle', 'rb') as load_file:
            map_builder_loaded = pickle.load(load_file)
            graph_params = map_builder_loaded.graph_params
            if len(graph_params) == 0:
                graph_params = {'points_inside': False, 'distance_delta': 150.0, 'weight_func_degree': 2.0,
                                'angle_of_vision': 30.0, 'weight_time_graph': 1.0, 'weight_course_graph': 0.1,
                                'search_algorithm': 'Dijkstra'}
    except FileNotFoundError or EOFError:
        graph_params = {'points_inside': False, 'distance_delta': 150.0, 'weight_func_degree': 2.0,
                        'angle_of_vision': 30.0, 'weight_time_graph': 1.0, 'weight_course_graph': 0.1,
                        'search_algorithm': 'Dijkstra'}
    return graph_params
