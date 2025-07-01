import io
import random
import time
import urllib.request

from cairo import ImageSurface
from flask import jsonify


def create_success_response(data, status_code=200):
    response = {
        "success": True,
        "data": data,
        "error": None
    }
    return jsonify(response), status_code


def create_error_response(data, error, status_code=400):
    response = {
        "success": False,
        "data": data,
        "error": error
    }
    return jsonify(response), status_code


def load_tile(tile, min_x, min_y, tile_size, headers):
    for _ in range(42):
        try:
            server = random.choice(['a', 'b', 'c'])
            url = 'http://{server}.tile.openstreetmap.org/{zoom}/{x}/{y}.png'.format(
                server=server,
                zoom=tile.z,
                x=tile.x,
                y=tile.y
            )
            request = urllib.request.Request(url=url, headers=headers)
            response = urllib.request.urlopen(request, timeout=5.0)
            img = ImageSurface.create_from_png(io.BytesIO(response.read()))
            return img, (tile.x - min_x) * tile_size[0], (tile.y - min_y) * tile_size[0]
        except:
            time.sleep(5)

    raise ConnectionError('Не удалось загрузить карту, openstreetmap прилег :(')
