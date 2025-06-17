import time

import numpy as np
from joblib import parallel_backend
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from DataMovements.data_movements import load_positions_cleaned, check_clusters, \
    store_clusters, store_avg_values, get_hash_value
from Visualization.visualization import MapRenderer


# from sklearn.neighbors import NearestNeighbors
# import numpy as np
# import matplotlib.pyplot as plt
# import statistics

def clustering(clustering_params):
    weight_distance = float(clustering_params['weight_distance'])
    weight_speed = float(clustering_params['weight_speed'])
    weight_course = float(clustering_params['weight_course'])
    eps = float(clustering_params['eps'])
    min_samples = int(clustering_params['min_samples'])
    metric_degree = float(clustering_params['metric_degree'])
    dataset_id = int(clustering_params['dataset_id'])

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
        df = load_positions_cleaned(dataset_id)

        df['sin_course'] = np.sin(np.deg2rad(df['course']))
        df['cos_course'] = np.cos(np.deg2rad(df['course']))

        min_lat = df['lat'].min()
        min_lon = df['lon'].min()
        max_lat = df['lat'].max()
        max_lon = df['lon'].max()

        dbscan_start_time = time.time()
        # Нормализуем данные, значительно увеличивает вычислительную эффективность
        scaler = StandardScaler()
        X = scaler.fit_transform(df[['lat', 'lon', 'speed', 'sin_course', 'cos_course']])  # Распараллеливаем вычисления
        weights = [
            weight_distance / (2 ** (1 / metric_degree)),
            weight_distance / (2 ** (1 / metric_degree)),
            weight_speed,
            weight_course / (2 ** (1 / metric_degree)),
            weight_course / (2 ** (1 / metric_degree))
        ]
        with parallel_backend('loky', n_jobs=-1):
            clusters = DBSCAN(eps=eps, min_samples=min_samples, metric='minkowski', p=metric_degree,
                              metric_params={'w': weights}).fit_predict(X)
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

    ds_hash_value = get_hash_value(dataset_id)
    map_renderer = MapRenderer(west=min_lat, south=min_lon, east=max_lat, north=max_lon, zoom=12, df=df,
                               cl_hash_id=cl_hash_id, ds_hash_value=ds_hash_value)
    map_renderer.clustering_params = clustering_params
    img_paths, result_clustering = map_renderer.create_clustered_map(dbscan_time=dbscan_time)

    return img_paths, result_clustering, map_renderer.geographic_extent_manual, cl_hash_id
