import math
import pandas as pd


def format_coordinate(coordinate):
    return round(float(coordinate), 7)


def get_coordinates(coords):
    if type(coords) is list:
        return [format_coordinate(c) for c in coords]
    elif type(coords) is str:
        return [format_coordinate(c.strip()) for c in coords.split(',')]


def delete_noise(df: pd.DataFrame()):
    return df.loc[(df['cluster'] != -1)].dropna(axis=0).reset_index(drop=True)


def astar_heuristic(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)
