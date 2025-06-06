import os
# from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash
from flask import jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from DB.model import db, User
from Main.main import call_clustering, load_clustering_params, call_find_path, load_graph_params

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'FeAF<j,f322AfHnE_VfCnB#'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'DB', 'TheWay.db')
db.init_app(app)
with app.app_context():
    db.create_all()

login_manager = LoginManager(app)
login_manager.login_view = 'login'
# ROLES = ('operator', 'drone')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# def role_required(role):
#     def decorator(f):
#         @wraps(f)
#         @login_required
#         def decorated_function(*args, **kwargs):
#             if current_user.role != role:
#                 return "Access denied", 403
#             return f(*args, **kwargs)
#
#         return decorated_function
#
#     return decorator


# operator_required = role_required('operator')
# drone_required = role_required('drone')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash("Неверное имя пользователя или пароль")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # role = request.form['role']
        # if role not in ROLES:
        #     flash("Invalid role")
        #     return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash("Пользователь с таким именем уже существует")
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('index'))
        # flash("Registered successfully please log in.")
        # return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# @app.route('/operator-zone')
# @operator_required
# def operator_zone():
#     return f"Welcome to operator zone, {current_user.username}"
#
#
# @app.route('/drone-zone')
# @drone_required
# def drone_zone():
#     return f"Welcome to drone zone, {current_user.username}"


@app.route('/post_graphs_parameters', methods=['POST'])
def get_graph():
    parameters_for_graph = request.get_json()

    start_long, start_lat = get_coordinates(parameters_for_graph['start_coords'])
    end_long, end_lat = get_coordinates(parameters_for_graph['end_coords'])
    coords = dict(start_lat=start_lat, start_long=start_long, end_lat=end_lat, end_long=end_long)
    del parameters_for_graph['start_coords']
    del parameters_for_graph['end_coords']

    for key in parameters_for_graph:
        if key != 'search_algorithm' and key != 'points_inside':
            parameters_for_graph[key] = float(parameters_for_graph[key])

    for key in coords:
        coords[key] = float(coords[key])

    # print(parameters_for_graph, coords)
    graph_data = call_find_path(parameters_for_graph, coords)
    return jsonify(graph_data)


def get_coordinates(coords):
    lat, long = coords.split(',')
    return lat, long


@app.route('/post_clustering_parameters', methods=['POST'])
def get_clusters():
    parameters_for_DBSCAN = request.get_json()
    # print(parameters_for_DBSCAN)

    for key in parameters_for_DBSCAN:
        if key != 'hull_type':
            parameters_for_DBSCAN[key] = float(parameters_for_DBSCAN[key])

    clusters_data = call_clustering(parameters_for_DBSCAN)
    return jsonify(clusters_data)


@app.route('/choose_dataset', methods=['POST'])
def choose_dataset():
    dataset_name = request.form.get('dataset_name')
    if not dataset_name:
        return jsonify(success=False, message='Датасет не выбран!')
    return jsonify(success=True, message=f'Выбран датасет: {dataset_name}')


@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    clustering_params = load_clustering_params()
    graph_params = load_graph_params()

    dev_datasets = {'all': ['акватория 1', 'акватория 2', 'акватория 3'], 'mine': ['акватория 1']}
    return render_template('index.html',
                           datasets=dev_datasets,
                           clustering_params=clustering_params,
                           graph_params=graph_params,
                           int=int,
                           len=len
                           )


if __name__ == '__main__':
    app.run()
