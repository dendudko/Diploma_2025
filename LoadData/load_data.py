import hashlib
import json
import numpy as np
import pandas as pd
from datetime import datetime

from DB.model import db, Hashes, Datasets, PositionsCleaned, Clusters, ClusterMembers, DatasetAnalysisLink


def fetch_datasets_for_user(user_id):
    """
    Извлекает датасеты для пользователя.
    Возвращает ID из таблицы Datasets, а не hash_id, для корректной идентификации в UI.
    """
    all_datasets = db.session.query(Datasets.id, Datasets.dataset_name).order_by(Datasets.dataset_name).all()
    mine_datasets = db.session.query(Datasets.id, Datasets.dataset_name).filter_by(user_id=user_id).order_by(
        Datasets.dataset_name).all()

    all_list = [{'id': ds.id, 'name': ds.dataset_name} for ds in all_datasets]
    mine_list = [{'id': ds.id, 'name': ds.dataset_name} for ds in mine_datasets]

    return {'all': all_list, 'mine': mine_list}


def read_csv_or_xlsx(file):
    """Читает файл в DataFrame в зависимости от расширения."""
    if file.filename.endswith('.csv'):
        return pd.read_csv(file, sep=';', decimal=',')
    elif file.filename.endswith('.xlsx'):
        return pd.read_excel(file)
    raise ValueError("Неподдерживаемый формат файла. Пожалуйста, используйте .csv или .xlsx")


def integrity_check(hash_value, dataset_name):
    """
    Проверяет, существует ли уже датасет с таким же хэшем исходных данных или названием.
    """
    hash_obj = db.session.query(Hashes).filter_by(hash_value=hash_value).first()
    if hash_obj and hash_obj.source_of_datasets:
        existing_dataset = hash_obj.source_of_datasets[0]
        return True, f'Датасет с таким содержимым был создан ранее: {existing_dataset.dataset_name}'

    dataset_obj = db.session.query(Datasets).filter_by(dataset_name=dataset_name).first()
    if dataset_obj:
        return False, 'Название датасета не уникально!'

    return None


def store_dataset(df: pd.DataFrame, dataset_name, user_id, hash_value):
    """
    Сохраняет исходные, обработанные данные (позиции) и информацию о датасете.
    """
    new_hash = Hashes(hash_value=hash_value, timestamp=datetime.now(), params=None)
    db.session.add(new_hash)
    db.session.flush()

    new_dataset = Datasets(dataset_name=dataset_name, user_id=user_id, source_hash_id=new_hash.hash_id)
    db.session.add(new_dataset)

    df['hash_id'] = new_hash.hash_id
    records = df.to_dict(orient='records')
    db.session.bulk_insert_mappings(PositionsCleaned, records)

    db.session.commit()


def process_and_store_dataset(df_data, df_marine, dataset_name, user_id, interpolation, max_gap_minutes: int = 30):
    try:
        df_data = read_csv_or_xlsx(df_data)
        df_marine = read_csv_or_xlsx(df_marine)
        if not {'id_marine', 'lat', 'lon', 'speed', 'course', 'date_add', 'age'}.issubset(set(df_data.columns.tolist())):
            raise Exception('проверяйте формат файла с данными о движении.')
        if not {'id_marine', 'port', 'length'}.issubset(set(df_marine.columns.tolist())):
            raise Exception('проверяйте формат файла с данными о судах.')

        if max_gap_minutes:
            max_gap_minutes = int(max_gap_minutes)

        hash_value = hashlib.md5(
            (df_data.to_csv() + df_marine.to_csv() + str(interpolation) + str(max_gap_minutes)).encode(
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

                # КОРРЕКТНАЯ интерполяция курса:
                for grp, sub_g in g.groupby('gap_group'):
                    mask = sub_g[['course']].notna().any(axis=1)
                    if mask.sum() >= 2:
                        # Переводим курс в синус и косинус
                        sin_course = np.sin(np.deg2rad(sub_g['course']))
                        cos_course = np.cos(np.deg2rad(sub_g['course']))
                        # Интерполируем синус и косинус
                        sin_course_interp = sin_course.interpolate(method='time')
                        cos_course_interp = cos_course.interpolate(method='time')
                        # Восстанавливаем курс
                        course_interp = np.rad2deg(np.arctan2(sin_course_interp, cos_course_interp))
                        course_interp = (course_interp + 360) % 360
                        g.loc[sub_g.index, 'course'] = course_interp

                g = g.drop(['gap_group'], axis=1)
                return g

            df_data = df_data.groupby('id_marine').apply(interpolate_with_gap)

        df_data = df_data[['lat', 'lon', 'speed', 'course']].dropna(axis=0).drop_duplicates()
        df_data = df_data.rename(columns={'lat': 'latitude', 'lon': 'longitude'})

        store_dataset(df_data, dataset_name, user_id, hash_value)

        return True, f'Создан датасет: {dataset_name}'

    except Exception as exc:
        db.session.rollback()
        error_message = exc.args[0] if exc.args else str(exc)
        return False, f'Ошибка при создании датасета: {error_message}'


# --- Функции для работы с кластеризацией ---
def load_positions_cleaned(dataset_id):
    """
    Загружает очищенные позиции для выбранного пользователем датасета.
    Принимает ID из таблицы Datasets.
    """
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
        ).filter_by(hash_id=dataset.source_hash_id).statement,  # Используем source_hash_id
        db.engine
    )


def check_clusters(clustering_params: dict):
    """
    Проверяет, существует ли уже результат кластеризации с заданными параметрами,
    игнорируя параметр 'hull_type'.
    """
    params_for_hashing = {k: v for k, v in clustering_params.items() if k != 'hull_type'}
    params_str = json.dumps(params_for_hashing, sort_keys=True)
    hash_value = hashlib.md5(params_str.encode('utf-8')).hexdigest()

    hash_obj = db.session.query(Hashes).filter_by(hash_value=hash_value).first()

    if hash_obj:
        print(f"Найден существующий результат кластеризации с hash_id: {hash_obj.hash_id}")
        return hash_obj.hash_id, pd.read_sql(
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
            .filter(Clusters.hash_id == hash_obj.hash_id)
            .statement, db.engine)
    else:
        return None, None


def store_clusters(df_results: pd.DataFrame, clustering_params: dict):
    """
    Сохраняет результаты кластеризации и создает связь с исходным датасетом.
    """
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


# --- Функции для удаления ---

def delete_dataset_by_id(dataset_id, current_user_id):
    """
    Удаляет датасет, все связанные с ним АНАЛИЗЫ и исходные данные.
    """
    try:
        dataset_to_delete = db.session.get(Datasets, int(dataset_id))
        if not dataset_to_delete:
            return False, 'Датасет не найден.'

        dataset_name = dataset_to_delete.dataset_name

        if dataset_to_delete.user_id != current_user_id:
            return False, f'Отказано в доступе: вы не являетесь владельцем датасета {dataset_name}'

        source_hash = dataset_to_delete.source_hash

        analysis_hashes_to_delete = [link.analysis_hash for link in dataset_to_delete.analysis_links]

        for analysis_hash in analysis_hashes_to_delete:
            print(f"Удаляется связанный анализ с hash_id: {analysis_hash.hash_id}")
            db.session.delete(analysis_hash)

        if source_hash:
            print(f"Удаляются исходные данные с hash_id: {source_hash.hash_id}")
            db.session.delete(source_hash)

        db.session.commit()
        return True, f'Датасет "{dataset_name}" и все связанные данные успешно удалены.'

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при удалении датасета {dataset_id}: {e}")
        return False, 'Произошла ошибка на сервере при удалении датасета.'
