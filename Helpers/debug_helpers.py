from datetime import datetime


def timer(func):
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        result = func(*args, **kwargs)
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"Время выполнения функции {func.__name__}: {duration.total_seconds()} секунд")
        return result

    return wrapper
