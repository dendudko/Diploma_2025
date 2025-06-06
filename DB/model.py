from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # role = db.Column(db.String(16), nullable=False)

    datasets = db.relationship('Datasets', back_populates='user_ref', cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Hashes(db.Model):
    __tablename__ = 'hashes'
    hash_id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)

    positions = db.relationship('PositionsCleaned', back_populates='hash_ref', cascade="all, delete-orphan")
    clusters = db.relationship('Clusters', back_populates='hash_ref', cascade="all, delete-orphan")
    polygons = db.relationship('ClPolygons', back_populates='hash_ref', cascade="all, delete-orphan")
    graphs = db.relationship('Graphs', back_populates='hash_ref', cascade="all, delete-orphan")
    datasets = db.relationship('Datasets', back_populates='hash_ref', cascade="all, delete-orphan")


class PositionsCleaned(db.Model):
    __tablename__ = 'positions_cleaned'
    position_id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id'), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    speed = db.Column(db.Float)
    course = db.Column(db.Float)

    hash_ref = db.relationship('Hashes', back_populates='positions')
    clusters = db.relationship('Clusters', back_populates='position_ref', cascade="all, delete-orphan")


class Datasets(db.Model):
    __tablename__ = 'datasets'
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id'), nullable=False, primary_key=True)
    dataset_name = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    user_ref = db.relationship('User', back_populates='datasets')
    hash_ref = db.relationship('Hashes', back_populates='datasets')


class Clusters(db.Model):
    __tablename__ = 'clusters'
    cluster_id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id'), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey('positions_cleaned.position_id'), nullable=False)

    hash_ref = db.relationship('Hashes', back_populates='clusters')
    position_ref = db.relationship('PositionsCleaned', back_populates='clusters')
    avg_values = db.relationship('ClAverageValues', back_populates='cluster_ref', uselist=False,
                                 cascade="all, delete-orphan")
    polygons = db.relationship('ClPolygons', back_populates='cluster_ref', cascade="all, delete-orphan")
    graphs = db.relationship('Graphs', back_populates='cluster_ref', cascade="all, delete-orphan")


class ClPolygons(db.Model):
    __tablename__ = 'cl_polygons'
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.cluster_id'), primary_key=True)
    boundary_latitude = db.Column(db.Float, nullable=False)
    boundary_longitude = db.Column(db.Float, nullable=False)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id'), nullable=False)

    cluster_ref = db.relationship('Clusters', back_populates='polygons')
    hash_ref = db.relationship('Hashes', back_populates='polygons')


class ClAverageValues(db.Model):
    __tablename__ = 'cl_average_values'
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.cluster_id'), primary_key=True)
    average_speed = db.Column(db.Float)
    average_course = db.Column(db.Float)

    cluster_ref = db.relationship('Clusters', back_populates='avg_values')


class Graphs(db.Model):
    __tablename__ = 'graphs'
    graph_id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.cluster_id'), nullable=False)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id'), nullable=False)

    cluster_ref = db.relationship('Clusters', back_populates='graphs')
    hash_ref = db.relationship('Hashes', back_populates='graphs')
    vertexes = db.relationship('GraphVertexes', back_populates='graph_ref', cascade="all, delete-orphan")
    edges = db.relationship('GraphEdges', back_populates='graph_ref', cascade="all, delete-orphan")


class GraphVertexes(db.Model):
    __tablename__ = 'graph_vertexes'
    vertex_id = db.Column(db.Integer, primary_key=True)
    graph_id = db.Column(db.Integer, db.ForeignKey('graphs.graph_id'), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    graph_ref = db.relationship('Graphs', back_populates='vertexes')
    edges_start = db.relationship('GraphEdges', back_populates='start_vertex',
                                  foreign_keys='GraphEdges.start_vertex_id', cascade="all, delete-orphan")
    edges_end = db.relationship('GraphEdges', back_populates='end_vertex', foreign_keys='GraphEdges.end_vertex_id',
                                cascade="all, delete-orphan")


class GraphEdges(db.Model):
    __tablename__ = 'graph_edges'
    edge_id = db.Column(db.Integer, primary_key=True)
    start_vertex_id = db.Column(db.Integer, db.ForeignKey('graph_vertexes.vertex_id'), nullable=False)
    end_vertex_id = db.Column(db.Integer, db.ForeignKey('graph_vertexes.vertex_id'), nullable=False)
    weight = db.Column(db.Float)

    start_vertex = db.relationship('GraphVertexes', foreign_keys=[start_vertex_id], back_populates='edges_start')
    end_vertex = db.relationship('GraphVertexes', foreign_keys=[end_vertex_id], back_populates='edges_end')
    graph_id = db.Column(db.Integer, db.ForeignKey('graphs.graph_id'), nullable=False)
    graph_ref = db.relationship('Graphs', back_populates='edges')
    routes = db.relationship('Routes', back_populates='edge_ref', cascade="all, delete-orphan")


class Routes(db.Model):
    __tablename__ = 'routes'
    route_id = db.Column(db.Integer, primary_key=True)
    edge_id = db.Column(db.Integer, db.ForeignKey('graph_edges.edge_id'), nullable=False)

    edge_ref = db.relationship('GraphEdges', back_populates='routes')
