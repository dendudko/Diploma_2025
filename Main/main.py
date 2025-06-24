from Clustering.clustering import clustering
from FindPath.find_path import find_path
from DataMovements.data_movements import process_and_store_dataset


def call_process_and_store_dataset(file_positions, file_marine, dataset_name, user_id, interpolation, max_gap_minutes):
    return process_and_store_dataset(file_positions, file_marine, dataset_name, user_id, interpolation, max_gap_minutes)


def call_clustering(clustering_params):
    return clustering(clustering_params)


def call_find_path(graph_params, clustering_params, cl_hash_id, gr_hash_id=None):
    return find_path(graph_params, clustering_params, cl_hash_id, gr_hash_id)


def load_clustering_params():
    return {'weight_distance': 3.5, 'weight_speed': 1.0, 'weight_course': 4.0, 'eps': 0.42,
            'min_samples': 60, 'metric_degree': 2.0, 'hull_type': 'concave_hull'}


def load_graph_params():
    return {'points_inside': False, 'distance_delta': 150.0, 'weight_func_degree': 2.0,
            'angle_of_vision': 30.0, 'weight_time_graph': 1.0, 'weight_course_graph': 0.1,
            'search_algorithm': 'Dijkstra'}
