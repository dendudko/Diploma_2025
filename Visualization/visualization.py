import concurrent.futures
import math
import os
import time

import mercantile
import numpy as np
import pandas
import shapely
from cairo import ImageSurface, FORMAT_ARGB32, Context, LINE_JOIN_ROUND, LINE_CAP_ROUND, LinearGradient

from DataMovements.data_movements import load_avg_values, load_polygon_geoms, store_polygon_geoms, store_extent
from Helpers.data_helpers import format_coordinate
from Helpers.vis_helpers import get_hours_minutes_str, generate_colors
from Helpers.web_helpers import load_tile


class MapRenderer:
    def __init__(self, west, south, east, north, zoom, df, cl_hash_id, ds_hash_value=None):
        # Задаваемые параметры
        self.left_top = None
        self.west = west
        self.south = south
        self.east = east
        self.north = north
        self.zoom = zoom
        self.df = df
        self.cl_hash_id = cl_hash_id
        self.ds_hash_value = ds_hash_value

        self.clustering_params = {}
        self.graph_params = {}

        self.df_points_on_image = pandas.DataFrame(columns=['x', 'y', 'speed', 'course', 'cluster'])
        self.polygon_bounds = {}
        self.polygon_buffers = {}
        self.intersections = {}
        self.intersection_bounds = {}
        self.intersection_points = []
        self.average_courses = {}
        self.average_speeds = {}

        try:
            self.noise_count = self.df['cluster'].value_counts()[-1]
        except KeyError:
            self.noise_count = 0
        self.total_count = len(self.df)
        self.cluster_count = max(self.df['cluster']) + 1
        self.colors = generate_colors(self.cluster_count)
        self.context = None
        self.map_image = None

        if (not os.path.exists(f'./static/images/clean/with_points_{self.ds_hash_value}.png') or
                not os.path.exists(f'./static/images/clean/{self.ds_hash_value}.png')):
            self.create_new_empty_map = True
        else:
            self.create_new_empty_map = False

        self.geographic_extent_manual = None

    def calculate_points_on_image(self):
        if len(self.df_points_on_image) == 0:
            # Добавляем объекты с пересчитанными координатами в df_points_on_image
            # gps в web-mercator
            xy = [mercantile.xy(x, y) for x, y in zip(self.df.lat, self.df.lon)]
            # переводим x, y в координаты изображения
            self.df_points_on_image.x = [(v[0] - self.left_top[0]) * self.kx for v in xy]
            self.df_points_on_image.y = [(v[1] - self.left_top[1]) * self.ky for v in xy]
            self.df_points_on_image.speed = self.df.speed
            self.df_points_on_image.course = self.df.course
            self.df_points_on_image.cluster = self.df.cluster

    def show_points(self, frac=1.0):
        for row in self.df_points_on_image.sample(frac=frac).itertuples(index=False):
            if int(row[4]) == -1:
                red = 0
                green = 0
                blue = 0
                alpha = 0.25
                r = 2
            else:
                red = self.colors[int(row[4])][0]
                green = self.colors[int(row[4])][1]
                blue = self.colors[int(row[4])][2]
                alpha = 1
                r = 2
            self.context.arc(row[0], row[1], r, 0 * math.pi / 180, 360 * math.pi / 180)
            self.context.set_source_rgba(red, green, blue, alpha)
            self.context.fill()

            # Рисуем линии, отображающие направление, стрелки перегружают картинку, будут просто линии)
            self.context.set_line_width(1.5)
            self.context.move_to(row[0], row[1])
            # Курс отсчитывается по часовой стрелке от направления на север, движение правостороннее
            angle = math.radians(row[3] - 90)
            line_length = row[2] / 10
            self.context.line_to(row[0] + line_length * math.cos(angle), row[1] + line_length * math.sin(angle))
            self.context.stroke()

    def process_polygon(self, coords):
        if len(coords) < 3:
            return None, None
        polygon_geom = shapely.Polygon(coords)
        if self.clustering_params['hull_type'] == 'convex_hull':
            polygon_geom2 = polygon_geom.convex_hull
        elif self.clustering_params['hull_type'] == 'concave_hull':
            polygon_geom2 = shapely.concave_hull(polygon_geom, ratio=0.5)
        else:
            polygon_geom2 = None

        if isinstance(polygon_geom2, shapely.Polygon):
            a, b = polygon_geom2.exterior.coords.xy
            bounds = tuple(zip(a, b))
            buffer = shapely.Polygon(bounds).buffer(1e-9)
            return bounds, buffer
        return None, None

    def show_polygons(self):
        polygon_geoms = load_polygon_geoms(self.cl_hash_id)
        if not polygon_geoms:
            polygon_geoms = {}
            for cluster in range(self.cluster_count):
                polygon = self.df_points_on_image.where(self.df_points_on_image['cluster'] == cluster).dropna(how='any')
                coords = list(zip(polygon['x'].values.tolist(), polygon['y'].values.tolist()))
                if len(coords) < 3:
                    continue
                bounds, buffer = self.process_polygon(coords)
                if bounds is not None:
                    self.polygon_bounds[cluster] = bounds
                    self.polygon_buffers[cluster] = buffer
                    # Сохраняем исходные координаты (до оболочки)
                    polygon_geom = shapely.Polygon(coords)
                    a1, b1 = polygon_geom.exterior.coords.xy
                    polygon_geoms[cluster] = list(zip(a1, b1))
            store_polygon_geoms(polygon_geoms, self.cl_hash_id)
        else:
            for cluster, coords in polygon_geoms.items():
                bounds, buffer = self.process_polygon(coords)
                if bounds is not None:
                    self.polygon_bounds[cluster] = bounds
                    self.polygon_buffers[cluster] = buffer

        for key, polygon_bound in self.polygon_bounds.items():
            red = self.colors[key][0]
            green = self.colors[key][1]
            blue = self.colors[key][2]
            alpha = 0.25
            self.context.set_source_rgba(red, green, blue, alpha)
            for dot in polygon_bound:
                self.context.line_to(dot[0], dot[1])
            self.context.fill_preserve()
            # Дополнительно выделяю границу полигона
            self.context.set_line_width(1.5)
            self.context.set_source_rgba(red, green, blue, 1)
            self.context.stroke()

    def show_intersections(self):
        # Ищем и отображаем пересечения полигонов
        if len(self.intersections) == 0 or len(self.intersection_bounds) == 0:
            keys = list(self.polygon_bounds.keys())
            for i in range(len(keys)):
                key_i = keys[i]
                for j in range(i + 1, len(keys)):
                    key_j = keys[j]
                    if shapely.intersects(shapely.Polygon(self.polygon_bounds[key_i]),
                                          shapely.Polygon(self.polygon_bounds[key_j])):
                        self.intersections[key_i, key_j] = (
                            shapely.intersection(shapely.Polygon(self.polygon_bounds[key_i]),
                                                 shapely.Polygon(self.polygon_bounds[key_j])))

            for key, intersection in self.intersections.items():
                if isinstance(intersection, shapely.Polygon):
                    a, b = intersection.exterior.coords.xy
                    self.intersection_bounds[key] = (tuple(list(zip(a, b))))
                elif isinstance(intersection, shapely.Point):
                    a, b = intersection.coords.xy
                    self.intersection_bounds[key] = (tuple(list(zip(a, b))))
                # Обработка множества пересечений двух полигонов при вогнутой оболочке
                elif isinstance(intersection, (shapely.GeometryCollection, shapely.MultiPolygon)):
                    for i, intersection_i in enumerate(intersection.geoms):
                        if isinstance(intersection_i, shapely.Polygon):
                            a, b = intersection_i.exterior.coords.xy
                            self.intersection_bounds[key + (i,)] = tuple(list(zip(a, b)))
                        elif isinstance(intersection_i, shapely.Point):
                            a, b = intersection_i.coords.xy
                            self.intersection_bounds[key + (i,)] = (tuple(list(zip(a, b))))

        for key, intersection_bound in self.intersection_bounds.items():
            red = 0
            green = 0
            blue = 0
            alpha = 0.1
            self.context.set_source_rgba(red, green, blue, alpha)
            for dot in intersection_bound:
                self.context.line_to(dot[0], dot[1])
            self.context.fill()

    def show_intersection_points(self):
        # Расстояние между точками в пересечении
        distance_delta = self.graph_params['distance_delta']
        # Накидываем точки на границу пересечения полигонов
        if len(self.intersection_points) == 0:
            for key, intersection_bound in self.intersection_bounds.items():
                if len(intersection_bound) > 1:
                    distances = np.arange(0, shapely.LineString(intersection_bound).length, distance_delta)
                    self.intersection_points.extend(
                        [shapely.LineString(intersection_bound).interpolate(distance) for distance in
                         distances])
                else:
                    self.intersection_points.append(shapely.Point(intersection_bound))

            if self.graph_params['points_inside']:
                try:
                    def flatten_geometrycollection(geom):
                        if isinstance(geom, (shapely.GeometryCollection, shapely.MultiPolygon, shapely.MultiPoint)):
                            flattened_list = []
                            for g in geom.geoms:
                                flattened_list.extend(flatten_geometrycollection(g))
                            return flattened_list
                        else:
                            return [geom]

                    gc = shapely.GeometryCollection(list(self.intersections.values()))
                    flat_gc = flatten_geometrycollection(gc)
                    all_intersections = shapely.GeometryCollection(flat_gc)

                    x_min, y_min, x_max, y_max = all_intersections.bounds
                    current_y = y_min - distance_delta
                    calculated_points = []
                    while current_y <= y_max:
                        current_y += distance_delta
                        current_x = x_min - distance_delta
                        while current_x <= x_max:
                            current_x += distance_delta
                            calculated_points.append(shapely.Point(current_x, current_y))
                    calculated_multi_point = shapely.MultiPoint(calculated_points)
                    actual_multi_point = shapely.MultiPoint(
                        [point for point in set(flatten_geometrycollection(
                            shapely.GeometryCollection(
                                [i.intersection(calculated_multi_point) for i in all_intersections.geoms]))) if
                         not point.is_empty])
                    actual_multi_point = actual_multi_point.geoms
                    self.intersection_points.extend(actual_multi_point)
                except Exception as exc:
                    print(f'При добавлении точек внутрь пересечений что-то пошло не так:\n{str(exc)}')

        for point in self.intersection_points:
            self.context.set_line_width(1.5)
            self.context.arc(point.x, point.y, 2, 0 * math.pi / 180, 360 * math.pi / 180)
            self.context.set_source_rgba(0, 255, 255, 1)
            self.context.stroke()

    def show_average_values(self):
        avg_values = load_avg_values(self.cl_hash_id)
        self.average_courses = {}
        self.average_speeds = {}
        for cluster_num, average_course, average_speed in avg_values:
            self.average_courses[cluster_num] = average_course
            self.average_speeds[cluster_num] = average_speed

        for key, polygon_bound in self.polygon_bounds.items():
            center = shapely.centroid(shapely.Polygon(polygon_bound))

            arrow_length = self.average_speeds[key]
            arrow_angle = math.radians(self.average_courses[key] - 90)
            arrowhead_angle = math.pi / 12
            arrowhead_length = 30

            self.context.move_to(center.x, center.y)  # move to center of polygon
            self.context.rel_move_to(-arrow_length * math.cos(arrow_angle) / 2,
                                     -arrow_length * math.sin(arrow_angle) / 2)
            self.context.rel_line_to(arrow_length * math.cos(arrow_angle), arrow_length * math.sin(arrow_angle))
            self.context.rel_move_to(-arrowhead_length * math.cos(arrow_angle - arrowhead_angle),
                                     -arrowhead_length * math.sin(arrow_angle - arrowhead_angle))
            self.context.rel_line_to(arrowhead_length * math.cos(arrow_angle - arrowhead_angle),
                                     arrowhead_length * math.sin(arrow_angle - arrowhead_angle))
            self.context.rel_line_to(-arrowhead_length * math.cos(arrow_angle + arrowhead_angle),
                                     -arrowhead_length * math.sin(arrow_angle + arrowhead_angle))

            red = self.colors[key][0]
            green = self.colors[key][1]
            blue = self.colors[key][2]
            self.context.set_source_rgba(red, green, blue, 1)
            self.context.set_line_width(10)
            self.context.stroke()

    def save_clustered_image(self, save_mode):
        file_path = (f'./static/images/clustered/'
                     f'{str(save_mode)}_{str(time.time_ns())}.png')
        with open(file_path, 'wb') as f:
            self.map_image.write_to_png(f)
        f.close()
        return file_path

    def create_empty_map(self):
        if self.create_new_empty_map:
            tile_size = (256, 256)
            tiles = list(mercantile.tiles(self.west, self.south, self.east, self.north, self.zoom))

            min_x = min([t.x for t in tiles])
            min_y = min([t.y for t in tiles])
            max_x = max([t.x for t in tiles])
            max_y = max([t.y for t in tiles])

            # создаем пустое изображение в которое как мозаику будем вставлять тайлы
            self.map_image = ImageSurface(
                FORMAT_ARGB32,
                tile_size[0] * (max_x - min_x + 1),
                tile_size[1] * (max_y - min_y + 1)
            )

            ctx = Context(self.map_image)

            headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'
                                     'AppleWebKit/537.11 (KHTML, like Gecko)'
                                     'Chrome/23.0.1271.64 Safari/537.11',
                       'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                       'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                       'Accept-Encoding': 'none',
                       'Accept-Language': 'en-US,en;q=0.8',
                       'Connection': 'keep-alive'}

            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [executor.submit(load_tile, tile, min_x, min_y, tile_size, headers) for tile in tiles]
                for future in concurrent.futures.as_completed(futures):
                    img, x, y = future.result()
                    ctx.set_source_surface(img, x, y)
                    ctx.paint()

            # рассчитываем коэффициенты
            bounds = {
                "left": min([mercantile.xy_bounds(t).left for t in tiles]),
                "right": max([mercantile.xy_bounds(t).right for t in tiles]),
                "bottom": min([mercantile.xy_bounds(t).bottom for t in tiles]),
                "top": max([mercantile.xy_bounds(t).top for t in tiles]),
            }

            # коэффициенты скалирования по оси x и y
            self.kx = self.map_image.get_width() / (bounds['right'] - bounds['left'])
            self.ky = self.map_image.get_height() / (bounds['top'] - bounds['bottom'])

            # пересчитываем размеры по которым будем обрезать
            self.left_top = mercantile.xy(self.west, self.north)
            right_bottom = mercantile.xy(self.east, self.south)
            offset_left = (self.left_top[0] - bounds['left']) * self.kx
            offset_top = (bounds['top'] - self.left_top[1]) * self.ky
            offset_right = (bounds['right'] - right_bottom[0]) * self.kx
            offset_bottom = (right_bottom[1] - bounds['bottom']) * self.ky

            # обрезанное изображение
            map_image_clipped = ImageSurface(
                FORMAT_ARGB32,
                self.map_image.get_width() - int(offset_left + offset_right),
                self.map_image.get_height() - int(offset_top + offset_bottom),
            )

            # вставляем кусок исходного изображения
            ctx = Context(map_image_clipped)
            ctx.set_source_surface(self.map_image, -offset_left, -offset_top)
            ctx.paint()
            self.map_image = map_image_clipped
        else:
            self.map_image = ImageSurface.create_from_png(f'./static/images/clean/{self.ds_hash_value}.png')

        # рассчитываем координаты углов в веб-меркаторе
        self.left_top = tuple(mercantile.xy(self.west, self.north))
        right_bottom = tuple(mercantile.xy(self.east, self.south))

        # Это для малышей беспилотников и клиентской карты,
        # обновляется моментально, пытаться грузить из БД бессмысленно
        if not self.geographic_extent_manual:
            self.geographic_extent_manual = [
                self.left_top[0],
                right_bottom[1],
                right_bottom[0],
                self.left_top[1]
            ]
            dataset_id = int(self.clustering_params['dataset_id'])
            store_extent(self.geographic_extent_manual, dataset_id)

        # рассчитываем коэффициенты
        self.kx = self.map_image.get_width() / (right_bottom[0] - self.left_top[0])
        self.ky = self.map_image.get_height() / (right_bottom[1] - self.left_top[1])

        # Сохраняем результат
        if self.create_new_empty_map:
            with open(f'./static/images/clean/{self.ds_hash_value}.png', 'wb') as f:
                self.map_image.write_to_png(f)
                f.close()

        self.context = Context(self.map_image)

    def create_empty_map_with_points(self):
        if self.create_new_empty_map:
            context = Context(self.map_image)
            for row in self.df_points_on_image.itertuples(index=False):
                context.arc(row[0], row[1], 2, 0 * math.pi / 180, 360 * math.pi / 180)
                context.set_source_rgba(255, 0, 0, 0.7)
                context.fill()
                # Рисуем линии, отображающие направление, стрелки перегружают картинку, будут просто линии)
                context.set_line_width(1.5)
                context.move_to(row[0], row[1])
                # Курс отсчитывается по часовой стрелке от направления на север, движение правостороннее
                angle = math.radians(row[3] - 90)
                line_length = row[2] / 10
                context.line_to(row[0] + line_length * math.cos(angle), row[1] + line_length * math.sin(angle))
                context.stroke()
            # Сохраняем результат
            with open(f'./static/images/clean/with_points_{self.ds_hash_value}.png', 'wb') as f:
                self.map_image.write_to_png(f)

            self.map_image = ImageSurface.create_from_png(f'./static/images/clean/{self.ds_hash_value}.png')
            self.context = Context(self.map_image)

    def get_img_coords_from_lat_lon(self, lat, lon):
        # gps в меркатор
        xy = mercantile.xy(lon, lat)
        # переводим xy в координаты изображения
        x = (xy[0] - self.left_top[0]) * self.kx
        y = (xy[1] - self.left_top[1]) * self.ky
        return x, y

    def get_lat_lon_from_img_coords(self, x, y):
        web_x = x / self.kx + self.left_top[0]
        web_y = y / self.ky + self.left_top[1]
        lon, lat = mercantile.lnglat(web_x, web_y)
        return lat, lon

    def show_start_and_end_points(self, start_point, end_point):
        self.context.set_line_width(0)
        self.context.set_source_rgba(255, 255, 255, 1)
        self.context.arc(start_point.x, start_point.y, 9, 0 * math.pi / 180, 360 * math.pi / 180)
        self.context.arc(end_point.x, end_point.y, 9, 0 * math.pi / 180, 360 * math.pi / 180)
        self.context.fill()
        self.context.set_source_rgba(255, 0, 0, 1)
        self.context.arc(start_point.x, start_point.y, 6, 0 * math.pi / 180, 360 * math.pi / 180)
        self.context.fill()
        self.context.set_source_rgba(0, 0, 0, 1)
        self.context.arc(end_point.x, end_point.y, 6, 0 * math.pi / 180, 360 * math.pi / 180)
        self.context.fill()

    def show_graph(self, graph, paths, build_graph_time, find_path_time, create_new_graph, drone_mode=False):
        result_graph = {}
        for path in paths:
            # Отрисовка черной линии
            self.context.set_line_join(LINE_JOIN_ROUND)
            self.context.set_line_width(18)
            self.context.set_source_rgba(0, 0, 0, 1)
            for node in path:
                self.context.line_to(node.x, node.y)
            self.context.stroke()
            # Отрисовка на черной линии зеленой
            self.context.set_line_width(10)
            self.context.set_line_cap(LINE_CAP_ROUND)
            angle_deviation_sum = 0
            distance = 0
            time_sum = 0
            angle_deviation_on_section = []
            speed_on_section = []
            distance_of_section = []
            for i in range(len(path) - 2):
                ln_gradient = LinearGradient(path[i].x, path[i].y, path[i + 1].x, path[i + 1].y)
                current_edge_data = graph.get_edge_data(path[i], path[i + 1])
                next_edge_data = graph.get_edge_data(path[i + 1], path[i + 2])

                angle_deviation_sum += current_edge_data['angle_deviation']
                distance += current_edge_data['distance']
                time_sum += current_edge_data['distance'] / current_edge_data['speed']

                angle_deviation_on_section.append(current_edge_data['angle_deviation'])
                speed_on_section.append(current_edge_data['speed'])
                distance_of_section.append(current_edge_data['distance'])

                color1 = current_edge_data['color']
                color2 = next_edge_data['color']
                line_length = shapely.LineString([path[i], path[i + 1]]).length
                if line_length > 30:
                    color_stop1 = (line_length - 15) / line_length
                    color_stop2 = (line_length - 5) / line_length
                    ln_gradient.add_color_stop_rgba(color_stop1, color1[0], color1[1], color1[2], color1[3])
                    ln_gradient.add_color_stop_rgba(color_stop2, color2[0], color2[1], color2[2], color2[3])
                else:
                    ln_gradient.add_color_stop_rgba(0, color1[0], color1[1], color1[2], color1[3])
                self.context.set_source(ln_gradient)
                self.context.move_to(path[i].x, path[i].y)
                self.context.line_to(path[i + 1].x, path[i + 1].y)
                self.context.stroke()

            last_edge_data = graph.get_edge_data(path[-2], path[-1])
            color = last_edge_data['color']
            self.context.set_source_rgba(color[0], color[1], color[2], color[3])
            self.context.move_to(path[-2].x, path[-2].y)
            self.context.line_to(path[-1].x, path[-1].y)
            self.context.stroke()

            angle_deviation_sum += last_edge_data['angle_deviation']
            distance += last_edge_data['distance']
            time_sum += last_edge_data['distance'] / last_edge_data['speed']

            angle_deviation_on_section.append(last_edge_data['angle_deviation'])
            speed_on_section.append(last_edge_data['speed'])
            distance_of_section.append(last_edge_data['distance'])

            angle_deviation_mean = angle_deviation_sum / (len(path) - 1)

            result_graph['Протяженность маршрута'] = f'{str(round(distance, 3))} (м. мили)'
            result_graph['Примерное время прохождения маршрута'] = f'{get_hours_minutes_str(time_sum)}'
            result_graph['Среднее отклонение от курсов на маршруте'] = f'{str(round(angle_deviation_mean, 1))}°'
            result_graph[
                'Протяженность участков'] = f'{[round(distance, 3) for distance in distance_of_section]} (м. мили)'
            result_graph['Скорость на участках'] = f'{[round(speed, 1) for speed in speed_on_section]} (узлы)'
            result_graph[
                'Отклонения от курсов на участках'] = f'{[round(angle, 1) for angle in angle_deviation_on_section]} (°)'
            result_graph['Характеристики графа'] = str(graph)
            route_points = [[format_coordinate(c) for c in self.get_lat_lon_from_img_coords(point.x, point.y)]
                            for point in path]
            result_graph['Точки маршрута'] = str(route_points)
            result_graph['Время построения графа'] = str(build_graph_time) + ' (секунды)'
            if not create_new_graph:
                result_graph['Время построения графа'] += ' *достроение'
            result_graph['Время планирования маршрута'] = str(find_path_time) + ' (секунды)'

            if drone_mode:
                drone_response = {
                    "route_points": [[format_coordinate(c) for c in self.get_lat_lon_from_img_coords(point.x, point.y)]
                                     for point in path],
                    "route_length_miles": round(distance, 3),
                    "route_duration_hours": round(time_sum, 2),
                    "route_sections_speed_knots": [round(speed, 1) for speed in speed_on_section]
                }
                result_graph['drone'] = drone_response

        return result_graph

    # Возможно стоит убрать мелкие кластеры...
    def create_clustered_map(self, dbscan_time):
        result_clustering = {}
        img_paths = []
        for save_mode in 'clusters', 'polygons':
            self.create_empty_map()
            self.calculate_points_on_image()
            self.create_empty_map_with_points()
            # frac - можно выбрать, какую долю объектов нанести на карту
            if save_mode == 'clusters':
                self.show_points(frac=1)
            elif save_mode == 'polygons':
                self.show_polygons()
                self.show_intersections()
                self.show_average_values()

            img_paths.append(self.save_clustered_image(save_mode))

        log = (f'Параметры для DBSCAN: {str(self.clustering_params)}\n'
               f'Всего кластеров: {str(self.cluster_count)}\n'
               f'Доля шума: {str(self.noise_count)} / {str(self.total_count)}\n'
               f'Время выполнения DBSCAN: {str(dbscan_time)} (секунды)\n\n')

        with open('./static/logs/DBSCAN_log.txt', 'a') as log_file:
            log_file.write(log)

        result_clustering['Всего кластеров'] = f'{str(self.cluster_count)}'
        result_clustering['Доля шума'] = f'{str(self.noise_count)} / {str(self.total_count)}'
        result_clustering['Время выполнения DBSCAN'] = f'{str(dbscan_time)} (секунды)'

        return img_paths, result_clustering
