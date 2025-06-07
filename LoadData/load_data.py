import os.path

import numpy as np
import pandas as pd
import hashlib
from app import db
from DB.model import Hashes, Datasets, PositionsCleaned


# pd.set_option('display.max_rows', None, 'display.max_columns', None)

# data_file_name - название файла с данными за день
# marine_file_name - название файла с данными о судах
# clean_{file_name} - подготовленный файл с данными за день
def load_data(data_file_name, marine_file_name, create_new_clean_xlsx=False):
    if os.path.exists('./DB/clean/clean_' + data_file_name) and not create_new_clean_xlsx:
        df = pd.read_excel('./DB/clean/clean_' + data_file_name)
        return df
    else:
        df = pd.read_excel('./DB/dirty/' + data_file_name)
        df_marine = pd.read_excel('./DB/dirty/' + marine_file_name)
        df = process_data(df, df_marine, data_file_name)
        return df


def process_data(df_data, df_marine, data_file_name):
    try:
        df_data = df_data[['id_marine', 'lat', 'lon', 'speed', 'course']]
        df_data = pd.merge(df_data, df_marine[['id_marine', 'port', 'length']], how='left', on='id_marine').dropna(
            axis=0)
        df_data = df_data.loc[(df_data['course'] != 511) & (df_data['port'] != 0) & (df_data['length'] != 0)]. \
            reset_index(drop=True)
        df_data = df_data[['lat', 'lon', 'speed', 'course']]
    except KeyError:
        pass
    df_data = df_data.drop_duplicates().dropna(axis=0)
    df_data.to_excel(f'./DB/clean/clean_{data_file_name}', index=False)
    return df_data


def read_csv_or_xlsx(file):
    df = None
    if file.filename.endswith('.csv'):
        df = pd.read_csv(file, sep=';', decimal=',')
    elif file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
    return df


def integrity_check(hash_value, dataset_name):
    hash_obj = db.session.query(Hashes).filter_by(hash=hash_value).first()
    if hash_obj is not None and hash_obj.datasets:
        dataset_name = hash_obj.datasets.dataset_name
        return True, f'Датасет был создан ранее, название: {dataset_name}'

    dataset_obj = db.session.query(Datasets).filter_by(dataset_name=dataset_name).first()
    if dataset_obj is not None:
        return False, f'Название датасета не уникально!'

    return None


def store_dataset(dataset: pd.DataFrame, dataset_name, user_id, hash_value):
    new_hash = Hashes(hash=hash_value, timestamp=pd.Timestamp.now())
    db.session.add(new_hash)
    db.session.flush()

    new_dataset = Datasets(hash_id=new_hash.hash_id, dataset_name=dataset_name, user_id=user_id)
    db.session.add(new_dataset)
    db.session.flush()

    dataset.insert(0, 'hash_id', new_hash.hash_id)
    records = dataset.to_dict(orient='records')

    db.session.bulk_insert_mappings(PositionsCleaned, records)
    db.session.commit()


def process_and_store_dataset(df_data, df_marine, dataset_name, user_id, interpolation, max_gap_minutes: int = 30):
    df_data = read_csv_or_xlsx(df_data)
    df_marine = read_csv_or_xlsx(df_marine)
    if max_gap_minutes:
        max_gap_minutes = int(max_gap_minutes)
    hash_value = hashlib.md5(
        (df_data.to_csv() + df_marine.to_csv() + str(interpolation) + str(max_gap_minutes)).encode('utf-8')).hexdigest()

    result_integrity_check = integrity_check(hash_value, dataset_name)
    if result_integrity_check is not None:
        return result_integrity_check

    df_data['timestamp'] = pd.to_datetime(df_data['date_add']) - pd.to_timedelta(df_data['age'], unit='m')
    df_data = pd.merge(df_data, df_marine[['id_marine', 'port', 'length']], how='left', on='id_marine').dropna(axis=0)
    df_data = df_data.loc[(df_data['course'] != 511) & (df_data['port'] != 0) & (df_data['length'] != 0)].reset_index(
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
