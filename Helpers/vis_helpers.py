import math


def get_hours_minutes_str(time_parameter):
    time_str = ''
    hours = math.floor(time_parameter)
    minutes = math.ceil((time_parameter % 1 * 60))
    if hours > 0:
        if 10 <= hours % 100 <= 20 or 5 <= hours % 10 <= 9 or hours % 10 == 0:
            time_str += str(hours) + ' часов '
        elif hours % 10 == 1:
            time_str += str(hours) + ' час '
        elif 2 <= hours % 10 <= 4:
            time_str += str(hours) + ' часа '

    if 10 <= minutes % 100 <= 20 or 5 <= minutes % 10 <= 9 or minutes % 10 == 0:
        time_str += str(minutes) + ' минут'
    elif minutes % 10 == 1:
        time_str += str(minutes) + ' минута'
    elif 2 <= minutes % 10 <= 4:
        time_str += str(minutes) + ' минуты'

    return time_str


def generate_colors(num_colors):
    colors = []
    # Golden ratio
    golden_ratio_conjugate = 0.618033988749895
    h = 0.0
    for i in range(num_colors):
        r, g, b = 0, 0, 0
        # HSL to RGB conversion
        h += golden_ratio_conjugate
        h %= 1
        hue = 360 * h
        saturation = 0.6
        lightness = 0.6
        c = (1 - abs(2 * lightness - 1)) * saturation
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = lightness - c / 2
        if hue < 60:
            r = c
            g = x
        elif hue < 120:
            r = x
            g = c
        elif hue < 180:
            g = c
            b = x
        elif hue < 240:
            g = x
            b = c
        elif hue < 300:
            r = x
            b = c
        else:
            r = c
            b = x
        r, g, b = r + m, g + m, b + m
        colors.append([r, g, b, 1])
    return colors
