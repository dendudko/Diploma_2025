import math
import time

import mercantile
import mpu
import networkx
import numpy as np
import shapely
import shapely.ops

from DataMovements.data_movements import load_clusters, get_hash_value, get_ds_hash_id, store_graph, check_graph, \
    get_hash_params, update_graph_edges, load_graph
from Helpers.data_helpers import get_coordinates, astar_heuristic, format_coordinate
from Visualization.visualization import MapRenderer


def find_path(graph_params, clustering_params, cl_hash_id, gr_hash_id=None):
    start_lon, start_lat = get_coordinates(graph_params['start_coords'])
    end_lon, end_lat = get_coordinates(graph_params['end_coords'])
    coords = dict(start_lat=start_lat, start_lon=start_lon, end_lat=end_lat, end_lon=end_lon)
    del graph_params['start_coords']
    del graph_params['end_coords']

    for key in graph_params:
        if key not in ('search_algorithm', 'points_inside', 'dataset_id', 'hull_type'):
            graph_params[key] = float(graph_params[key])

    _, df = load_clusters(cl_hash_id)
    min_lat = df['lat'].min()
    min_lon = df['lon'].min()
    max_lat = df['lat'].max()
    max_lon = df['lon'].max()
    dataset_id = int(graph_params['dataset_id'])
    ds_hash_id = get_ds_hash_id(dataset_id)
    ds_hash_value = get_hash_value(ds_hash_id)

    graph_builder = GraphBuilder(west=min_lat, south=min_lon, east=max_lat, north=max_lon, zoom=12, df=df,
                                 cl_hash_id=cl_hash_id, ds_hash_value=ds_hash_value)
    graph_builder.map_renderer.clustering_params = clustering_params
    graph_builder.map_renderer.graph_params = graph_params
    graph_builder.map_renderer.graph_params['hull_type'] = graph_builder.map_renderer.clustering_params['hull_type']
    return graph_builder.find_path(coords['start_lon'], coords['start_lat'], coords['end_lon'],
                                   coords['end_lat'], gr_hash_id)


class GraphBuilder:
    def __init__(self, west, south, east, north, zoom, df, cl_hash_id, ds_hash_value):
        self.map_renderer = MapRenderer(west=west, south=south, east=east, north=north,
                                        zoom=zoom, df=df, cl_hash_id=cl_hash_id, ds_hash_value=ds_hash_value)
        self.graph = networkx.DiGraph()

    def get_edge_distance(self, point_1, point_2):
        web_x1, web_y1 = (self.map_renderer.left_top[0] + point_1.x / self.map_renderer.kx,
                          self.map_renderer.left_top[1] + point_1.y / self.map_renderer.ky)
        web_x2, web_y2 = (self.map_renderer.left_top[0] + point_2.x / self.map_renderer.kx,
                          self.map_renderer.left_top[1] + point_2.y / self.map_renderer.ky)
        lon1, lat1 = mercantile.lnglat(web_x1, web_y1)
        lon2, lat2 = mercantile.lnglat(web_x2, web_y2)
        distance = mpu.haversine_distance((lat1, lon1), (lat2, lon2)) / 1.85
        return distance

    def get_nearest_poly_point(self, point):
        polygon_union = [shapely.Polygon(polygon) for polygon in self.map_renderer.polygon_bounds.values()]
        nearest_point = shapely.ops.nearest_points(shapely.ops.unary_union(polygon_union), point)[0]
        distance = self.get_edge_distance(point, nearest_point)
        self.graph.add_edge(point, nearest_point, weight=0, color=[1, 0, 0, 1], angle_deviation=0,
                            distance=distance, speed=15)
        self.graph.add_edge(nearest_point, point, weight=0, color=[1, 0, 0, 1], angle_deviation=0,
                            distance=distance, speed=15)
        return nearest_point

    def visit_point(self, current_point, rotation=0):
        # Угол обзора в градусах
        angle_of_vision = self.map_renderer.graph_params['angle_of_vision']

        available_directions = {}
        # Ищем точки с прямым доступом в точку Б
        interesting_points = 0
        for key in self.map_renderer.polygon_bounds.keys():
            if shapely.intersects(self.map_renderer.polygon_buffers[key], current_point):
                available_directions[key] = self.map_renderer.average_courses[key]

        angles = {point: (math.atan2(point.y - current_point.y, point.x - current_point.x)
                          + 2 * math.pi) % (math.pi * 2) for point in self.map_renderer.intersection_points}

        for key, direction in available_directions.items():
            angle_center = (direction - 90 - rotation + 360) % 360
            # Определяем границы видимости
            angle_left = angle_center - angle_of_vision / 2
            angle_right = angle_center + angle_of_vision / 2
            # Конвертируем углы в радианы
            angle_left_rad = math.radians(angle_left)
            angle_center_rad = math.radians(angle_center)
            angle_right_rad = math.radians(angle_right)

            try:
                current_angles_keys = []
                if self.map_renderer.clustering_params['hull_type'] == 'convex_hull':
                    current_angles_keys = shapely.intersection(
                        self.map_renderer.polygon_buffers[key], shapely.MultiPoint(list(angles.keys()))).geoms
                elif self.map_renderer.clustering_params['hull_type'] == 'concave_hull':
                    current_angles_keys_multipoint = shapely.intersection(
                        self.map_renderer.polygon_buffers[key], shapely.MultiPoint(list(angles.keys()))).geoms
                    current_angles_keys = [
                        point for point in current_angles_keys_multipoint
                        if shapely.contains(self.map_renderer.polygon_buffers[key],
                                            shapely.LineString([point, current_point]))]
            except AttributeError:
                continue

            for point in current_angles_keys:
                if angle_left_rad <= angles[point] <= angle_right_rad:
                    interesting_points += 1
                    # Вес = (abs(расстояние в милях / скорость в узлах * вес времени) ** p +
                    # + abs(разница направлений * вес направления) ** p) ^ 1/p
                    angle_deviation = math.degrees(abs(angles[point] - angle_center_rad))
                    distance = self.get_edge_distance(point, current_point)
                    speed = self.map_renderer.average_speeds[key] / 10
                    p = self.map_renderer.graph_params['weight_func_degree']
                    weight = np.power(
                        np.power(abs((distance / speed) * self.map_renderer.graph_params['weight_time_graph']), p) +
                        np.power(abs(angle_deviation * self.map_renderer.graph_params['weight_course_graph']), p),
                        1 / p)
                    if rotation == 180:
                        edge_end, edge_start = current_point, point
                    else:
                        edge_start, edge_end = current_point, point
                    # Обновляем вес существующего ребра, только если он больше нового
                    data = self.graph.get_edge_data(current_point, point)
                    if data is not None:
                        if data['weight'] > weight:
                            self.graph.add_edge(edge_start, edge_end, weight=weight,
                                                color=self.map_renderer.colors[key],
                                                angle_deviation=angle_deviation, distance=distance, speed=speed)
                    else:
                        self.graph.add_edge(edge_start, edge_end, weight=weight, color=self.map_renderer.colors[key],
                                            angle_deviation=angle_deviation, distance=distance, speed=speed)

        return interesting_points

    def recalculate_edges(self, gr_hash_id):
        p = self.map_renderer.graph_params['weight_func_degree']
        for edge in self.graph.edges:
            data = self.graph.get_edge_data(edge[0], edge[1])
            weight = np.power(
                np.power(abs((data['distance'] / data['speed']) * self.map_renderer.graph_params['weight_time_graph']),
                         p)
                + np.power(abs(data['angle_deviation'] * self.map_renderer.graph_params['weight_course_graph']), p),
                1 / p)
            self.graph.add_edge(edge[0], edge[1], weight=weight, color=data['color'],
                                angle_deviation=data['angle_deviation'], distance=data['distance'], speed=data['speed'])

        update_graph_edges(gr_hash_id, self.map_renderer.graph_params, self.graph)

    def build_graph(self, start_point=None, end_point=None, create_new_graph=False, drone_mode=False):
        build_graph_start_time = time.time()
        result_graph = {}
        end_point_saved = None
        graph_id = None
        points_to_delete = []
        # Обработка случая, когда точка А или Б не попала в полигон
        # Предполагаем, что скорость в таком случае 30 узлов
        end_point_in_poly = False
        start_point_in_poly = False
        for key in self.map_renderer.polygon_bounds.keys():
            if shapely.intersects(self.map_renderer.polygon_buffers[key], end_point):
                end_point_in_poly = True
            if shapely.intersects(self.map_renderer.polygon_buffers[key], start_point):
                start_point_in_poly = True

        if not start_point_in_poly:
            current_point = self.get_nearest_poly_point(start_point)
            points_to_delete.append(current_point)
        else:
            current_point = start_point
        points_to_delete.append(start_point)

        if not end_point_in_poly:
            end_point_saved = end_point
            end_point = self.get_nearest_poly_point(end_point)
            points_to_delete.append(end_point)
        points_to_delete.append(end_point_saved)

        # Если точки лежат в полигонах - добавляем их в точки пересечений (множество узлов)
        # Если не лежат - добавляем в точки пересечений ближайшие точки полигонов,
        # сами точки начала и конца будут только в графе
        if current_point not in self.map_renderer.intersection_points:
            self.map_renderer.intersection_points.append(current_point)
        if end_point not in self.map_renderer.intersection_points:
            self.map_renderer.intersection_points.append(end_point)
        self.graph.add_node(start_point)
        self.graph.add_node(end_point)

        start_interesting_points = self.visit_point(current_point)
        end_interesting_points = self.visit_point(end_point, rotation=180)

        if end_interesting_points != 0 and start_interesting_points != 0 and create_new_graph:
            for point in self.map_renderer.intersection_points:
                self.visit_point(point)

        if end_point_saved:
            end_point = end_point_saved

        build_graph_time = round(time.time() - build_graph_start_time, 3)

        # Вызов A* и Дейкстры, отрисовка пути
        try:
            find_path_start_time = time.time()
            paths = []
            # Длина пути только для сравнения алгоритмов поиска, считается по весам ребер
            if self.map_renderer.graph_params['search_algorithm'] == 'Dijkstra':
                # paths.append(networkx.dijkstra_path(self.graph, start_point, end_point))
                paths.append(networkx.bidirectional_dijkstra(self.graph, start_point, end_point)[1])
            elif self.map_renderer.graph_params['search_algorithm'] == 'A*':
                paths.append(networkx.astar_path(self.graph, start_point, end_point, heuristic=astar_heuristic))

            find_path_time = round(time.time() - find_path_start_time, 3)

            result_graph = self.map_renderer.show_graph(self.graph, paths, build_graph_time, find_path_time,
                                                        create_new_graph, drone_mode)

        except networkx.exception.NetworkXNoPath:
            result_graph['Error'] = 'Маршрут найти не удалось!'
            result_graph['Точка отправления'] = self.map_renderer.get_lat_lon_from_img_coords(start_point.x,
                                                                                              start_point.y)
            result_graph['Точка прибытия'] = self.map_renderer.get_lat_lon_from_img_coords(end_point.x,
                                                                                           end_point.y)
            if drone_mode:
                drone_response = {
                    "error": "Route not found.",
                    "start_point": [format_coordinate(c) for c in result_graph.get('Точка отправления')],
                    "end_point": [format_coordinate(c) for c in result_graph.get('Точка прибытия')]
                }
                result_graph['drone'] = drone_response

        # Выделение точек начала и конца
        self.map_renderer.show_start_and_end_points(start_point, end_point)

        # Удаляем начальный и конечный узлы,
        # чтобы в графе не копился мусор
        for point in set(points_to_delete):
            if point:
                self.graph.remove_node(point)
        # Если граф не был построен - обнуляем граф и его параметры
        if (start_interesting_points == 0 or end_interesting_points == 0) and create_new_graph:
            self.map_renderer.graph_params = {}
            self.graph = networkx.DiGraph()
        elif create_new_graph:
            graph_id = store_graph(self.graph,
                                   self.map_renderer.graph_params['dataset_id'],
                                   self.map_renderer.cl_hash_id,
                                   self.map_renderer)

        return result_graph, graph_id

    def find_path(self, x_start, y_start, x_end, y_end, gr_hash_id=None):
        self.map_renderer.create_empty_map()
        self.map_renderer.calculate_points_on_image()
        self.map_renderer.create_empty_map_with_points()
        self.map_renderer.show_polygons()
        self.map_renderer.show_intersections()
        self.map_renderer.show_average_values()

        if gr_hash_id:
            graph_id, _, self.graph = load_graph(gr_hash_id, self.map_renderer)
            drone_mode = True
        else:
            graph_id, gr_hash_id, self.graph = check_graph(self.map_renderer.graph_params, self.map_renderer)
            drone_mode = False

        if self.graph:
            self.map_renderer.intersection_points = list(self.graph.nodes)
            create_new_graph = False
            saved_params = get_hash_params(gr_hash_id)
            if (saved_params['weight_time_graph'] != self.map_renderer.graph_params['weight_time_graph'] or
                    saved_params['weight_course_graph'] != self.map_renderer.graph_params['weight_course_graph'] or
                    saved_params['weight_func_degree'] != self.map_renderer.graph_params['weight_func_degree']):
                self.recalculate_edges(gr_hash_id)
        else:
            self.graph = networkx.DiGraph()
            create_new_graph = True
        self.map_renderer.show_intersection_points()

        x_start, y_start = self.map_renderer.get_img_coords_from_lat_lon(x_start, y_start)
        x_end, y_end = self.map_renderer.get_img_coords_from_lat_lon(x_end, y_end)

        if not self.map_renderer.graph_params.get('search_algorithm'):
            self.map_renderer.graph_params['search_algorithm'] = 'Dijkstra'

        result_graph, new_graph_id = self.build_graph(shapely.Point(x_start, y_start),
                                                      shapely.Point(x_end, y_end), create_new_graph, drone_mode)
        if new_graph_id:
            graph_id = new_graph_id

        graph_img = self.map_renderer.save_clustered_image('path')

        result_graph['ID графа'] = graph_id
        with open('./static/logs/PATH_log.txt', 'a') as log_file:
            if drone_mode:
                log_file.write('Запрос от беспилотника!' + '\n')
            log_file.write('Параметры для графа: ' + str(self.map_renderer.graph_params) + '\n')
            for key, value in result_graph.items():
                if key != 'drone':
                    log_file.write(str(key) + ': ' + str(value) + '\n')
            log_file.write('\n')

        if drone_mode:
            return result_graph['drone']
        else:
            return graph_img, result_graph, self.map_renderer.geographic_extent_manual
