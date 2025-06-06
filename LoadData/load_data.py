import os.path
import pandas as pd


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


def dev_process_data(df_data, df_marine, data_file_name):
    df_data['timestamp'] = pd.to_datetime(df_data['date_add']) - pd.to_timedelta(df_data['age'], unit='m')
    df_data = pd.merge(df_data, df_marine[['id_marine', 'port', 'length']], how='left', on='id_marine').dropna(axis=0)
    df_data = df_data.loc[(df_data['course'] != 511) & (df_data['port'] != 0) & (df_data['length'] != 0)].reset_index(drop=True)
    df_data = df_data[['id_marine', 'lat', 'lon', 'speed', 'course', 'timestamp']]
    df_data = (
        df_data
        .drop_duplicates(subset=['id_marine', 'lat', 'lon', 'speed', 'course'], keep='first')
        .drop_duplicates(subset=['id_marine', 'timestamp'], keep='first')
        .dropna(axis=0)
    )
    df_data = df_data.sort_values(['id_marine', 'timestamp'])

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
        # Найдём места разрывов между исходными (не NaN) точками
        orig = g[g[['lat', 'lon', 'speed', 'course']].notna().all(axis=1)]
        # Разница между соседними исходными точками (в минутах)
        time_diff = orig.index.to_series().diff().dt.total_seconds() / 60
        # Группы между разрывами > 42 минут
        group_id = (time_diff > 42).cumsum().reindex(g.index, method='ffill').fillna(0).astype(int)
        g['gap_group'] = group_id.values

        for col in ['lat', 'lon', 'speed', 'course']:
            for grp, sub_g in g.groupby('gap_group'):
                # Только если в группе есть хотя бы две исходные точки
                mask = sub_g[[col]].notna().any(axis=1)
                if mask.sum() >= 2:
                    g.loc[sub_g.index, col] = sub_g[col].interpolate(method='time')
        g = g.drop(['gap_group'], axis=1)
        return g

    df_data = df_data.groupby('id_marine').apply(interpolate_with_gap)

    df_data = df_data[['lat', 'lon', 'speed', 'course']].dropna(axis=0).drop_duplicates()

    df_data.to_excel(f'../DB/clean/clean_{data_file_name}', index=False, engine='xlsxwriter')
    return df_data


if __name__ == '__main__':
    dfd_paths = ["D:/1ФЕФУ/Диплом(/Сангарский пролив/15.11.2015.csv",
                 "D:/1ФЕФУ/Диплом(/Сангарский пролив/16.11.2015.csv",
                 "D:/1ФЕФУ/Диплом(/Сангарский пролив/11.11.2015.csv",
                 "D:/1ФЕФУ/Диплом(/Сангарский пролив/12.11.2015.csv",
                 "D:/1ФЕФУ/Диплом(/Сангарский пролив/13.11.2015.csv",
                 "D:/1ФЕФУ/Диплом(/Сангарский пролив/14.11.2015.csv"]
    res = []
    for p in dfd_paths:
        res.append(pd.read_csv(p, sep=';', decimal=','))

    dfd = pd.concat(res)
    dfm = pd.read_csv('D:/1ФЕФУ/Диплом(/Сангарский пролив/marine.csv', sep=';', decimal=',')
    dev_process_data(dfd, dfm, 'all_merged.xlsx')
