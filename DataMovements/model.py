from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, ForeignKeyConstraint, Index
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    datasets = db.relationship('Datasets', back_populates='user', cascade="all, delete-orphan", passive_deletes=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Hashes(db.Model):
    __tablename__ = 'hashes'
    hash_id = db.Column(db.Integer, primary_key=True)
    hash_value = db.Column(db.String(64), unique=True, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    params = db.Column(JSON, nullable=True)

    positions = db.relationship('PositionsCleaned', back_populates='source_hash', cascade="all, delete-orphan",
                                passive_deletes=True)
    clusters = db.relationship('Clusters', back_populates='hash', cascade="all, delete-orphan", passive_deletes=True)
    graphs = db.relationship('Graphs', back_populates='hash', cascade="all, delete-orphan", passive_deletes=True)
    source_of_datasets = db.relationship('Datasets', back_populates='source_hash', cascade="all, delete-orphan",
                                         passive_deletes=True)
    analysis_links = db.relationship('DatasetAnalysisLink', back_populates='analysis_hash',
                                     cascade="all, delete-orphan", passive_deletes=True)


class Datasets(db.Model):
    __tablename__ = 'datasets'
    id = db.Column(db.Integer, primary_key=True)
    dataset_name = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False,
                        index=True)
    source_hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id', ondelete='CASCADE'), nullable=False,
                               index=True)
    extent_min_x = db.Column(db.Float, nullable=True)
    extent_min_y = db.Column(db.Float, nullable=True)
    extent_max_x = db.Column(db.Float, nullable=True)
    extent_max_y = db.Column(db.Float, nullable=True)

    user = db.relationship('User', back_populates='datasets')
    source_hash = db.relationship('Hashes', back_populates='source_of_datasets', foreign_keys=[source_hash_id])
    analysis_links = db.relationship('DatasetAnalysisLink', back_populates='dataset', cascade="all, delete-orphan",
                                     passive_deletes=True)


class DatasetAnalysisLink(db.Model):
    __tablename__ = 'dataset_analysis_link'
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id', ondelete='CASCADE'), primary_key=True)
    analysis_hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id', ondelete='CASCADE'), primary_key=True)

    dataset = db.relationship('Datasets', back_populates='analysis_links')
    analysis_hash = db.relationship('Hashes', back_populates='analysis_links')
    graphs = db.relationship('Graphs', back_populates='dataset_analysis_link', cascade="all, delete-orphan",
                             passive_deletes=True)


class PositionsCleaned(db.Model):
    __tablename__ = 'positions_cleaned'
    position_id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id', ondelete='CASCADE'), nullable=False,
                        index=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    speed = db.Column(db.Float)
    course = db.Column(db.Float)

    source_hash = db.relationship('Hashes', back_populates='positions')
    cluster_membership = db.relationship('ClusterMembers', back_populates='position', uselist=False,
                                         cascade="all, delete-orphan", passive_deletes=True)


class Clusters(db.Model):
    __tablename__ = 'clusters'
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id', ondelete='CASCADE'), primary_key=True)
    cluster_num = db.Column(db.Integer, primary_key=True)

    hash = db.relationship('Hashes', back_populates='clusters')
    members = db.relationship('ClusterMembers', back_populates='cluster', cascade="all, delete-orphan",
                              passive_deletes=True)
    avg_values = db.relationship('ClAverageValues', back_populates='cluster', uselist=False,
                                 cascade="all, delete-orphan", passive_deletes=True)
    polygons = db.relationship('ClPolygons', back_populates='cluster', cascade="all, delete-orphan",
                               passive_deletes=True)


class ClusterMembers(db.Model):
    __tablename__ = 'cluster_members'
    hash_id = db.Column(db.Integer, primary_key=True)
    cluster_num = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('positions_cleaned.position_id', ondelete='CASCADE'),
                            primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['hash_id', 'cluster_num'], ['clusters.hash_id', 'clusters.cluster_num'],
                             ondelete='CASCADE'),
        Index('idx_cm_hash_cluster', 'hash_id', 'cluster_num'),
    )
    cluster = db.relationship('Clusters', back_populates='members')
    position = db.relationship('PositionsCleaned', back_populates='cluster_membership')


class ClAverageValues(db.Model):
    __tablename__ = 'cl_average_values'
    hash_id = db.Column(db.Integer, primary_key=True)
    cluster_num = db.Column(db.Integer, primary_key=True)
    average_speed = db.Column(db.Float)
    average_course = db.Column(db.Float)

    __table_args__ = (
        ForeignKeyConstraint(['hash_id', 'cluster_num'], ['clusters.hash_id', 'clusters.cluster_num'],
                             ondelete='CASCADE'),
        Index('idx_clav_hash_cluster', 'hash_id', 'cluster_num'),
    )
    cluster = db.relationship('Clusters', back_populates='avg_values')


class ClPolygons(db.Model):
    __tablename__ = 'cl_polygons'
    polygon_point_id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.String(64), nullable=False)
    cluster_num = db.Column(db.Integer, nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(['hash_id', 'cluster_num'], ['clusters.hash_id', 'clusters.cluster_num'],
                             ondelete='CASCADE'),
        Index('idx_clp_hash_cluster', 'hash_id', 'cluster_num'),
    )
    cluster = db.relationship('Clusters', back_populates='polygons')


class Graphs(db.Model):
    __tablename__ = 'graphs'
    graph_id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.Integer, db.ForeignKey('hashes.hash_id', ondelete='CASCADE'), index=True)
    dataset_id = db.Column(db.Integer, nullable=False)
    analysis_hash_id = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(['dataset_id', 'analysis_hash_id'],
                             ['dataset_analysis_link.dataset_id', 'dataset_analysis_link.analysis_hash_id'],
                             ondelete='CASCADE'),
        Index('idx_graphs_dataset_analysis', 'dataset_id', 'analysis_hash_id'),
    )
    hash = db.relationship('Hashes', back_populates='graphs')
    dataset_analysis_link = db.relationship('DatasetAnalysisLink', back_populates='graphs')
    vertexes = db.relationship('GraphVertexes', back_populates='graph', cascade="all, delete-orphan",
                               passive_deletes=True)
    edges = db.relationship('GraphEdges', back_populates='graph', cascade="all, delete-orphan", passive_deletes=True)
    approved_graphs = db.relationship('ApprovedGraphs', back_populates='graph', cascade="all, delete-orphan",
                                      passive_deletes=True)


class ApprovedGraphs(db.Model):
    __tablename__ = 'approved_graphs'
    graph_id = db.Column(db.Integer, db.ForeignKey('graphs.graph_id', ondelete='CASCADE'), primary_key=True)
    graph = db.relationship('Graphs', back_populates='approved_graphs')


class GraphVertexes(db.Model):
    __tablename__ = 'graph_vertexes'
    vertex_id = db.Column(db.Integer, primary_key=True)
    graph_id = db.Column(db.Integer, db.ForeignKey('graphs.graph_id', ondelete='CASCADE'), nullable=False,
                         index=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    graph = db.relationship('Graphs', back_populates='vertexes')
    edges_start = db.relationship('GraphEdges', back_populates='start_vertex',
                                  foreign_keys='GraphEdges.start_vertex_id', cascade="all, delete-orphan",
                                  passive_deletes=True)
    edges_end = db.relationship('GraphEdges', back_populates='end_vertex', foreign_keys='GraphEdges.end_vertex_id',
                                cascade="all, delete-orphan", passive_deletes=True)


class GraphEdges(db.Model):
    __tablename__ = 'graph_edges'
    edge_id = db.Column(db.Integer, primary_key=True)
    start_vertex_id = db.Column(db.Integer, db.ForeignKey('graph_vertexes.vertex_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    end_vertex_id = db.Column(db.Integer, db.ForeignKey('graph_vertexes.vertex_id', ondelete='CASCADE'), nullable=False,
                              index=True)
    distance = db.Column(db.Float)
    speed = db.Column(db.Float)
    weight = db.Column(db.Float)
    color = db.Column(db.String)
    angle_deviation = db.Column(db.Float)
    graph_id = db.Column(db.Integer, db.ForeignKey('graphs.graph_id', ondelete='CASCADE'), nullable=False,
                         index=True)

    start_vertex = db.relationship('GraphVertexes', foreign_keys=[start_vertex_id], back_populates='edges_start')
    end_vertex = db.relationship('GraphVertexes', foreign_keys=[end_vertex_id], back_populates='edges_end')
    graph = db.relationship('Graphs', back_populates='edges')
    routes = db.relationship('Routes', back_populates='edge', cascade="all, delete-orphan", passive_deletes=True)


class Routes(db.Model):
    __tablename__ = 'routes'
    route_id = db.Column(db.Integer, primary_key=True)
    edge_id = db.Column(db.Integer, db.ForeignKey('graph_edges.edge_id', ondelete='CASCADE'), nullable=False,
                        index=True)

    edge = db.relationship('GraphEdges', back_populates='routes')
