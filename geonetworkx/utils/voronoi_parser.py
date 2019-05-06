"""
    File name: VoronoiParser
    Author: Artelys - Hugo Chareyre
    Date last modified: 21/11/2018
    Python Version: 3.6
"""
import numpy as np
from scipy.spatial import Voronoi, ConvexHull
from shapely.geometry import Polygon, box, Point, MultiLineString, LineString, MultiPoint
import geopandas as gpd
from itertools import chain
from typing import Union


GenericLine = Union[LineString, MultiLineString]


class VoronoiParser:
    """Add-on for the scipy.spatial Voronoi tool. It computes the voronoi cells within a bounding box."""

    def __init__(self, points, bounding_box_coords):
        """Constructor of the voronoi parser. It takes the points to compute and a bounding box representing the study
        area."""
        convex_hull = ConvexHull(points)
        self.hull_polygon = Polygon(
            [(x, y) for x, y in zip(points[convex_hull.vertices, 0], points[convex_hull.vertices, 1])])
        self.voronoi_obj = Voronoi(points)
        self.ridges_coords = None
        self.all_regions_coords = None
        self.compute_ridges_coords()
        diagonal_length = np.linalg.norm(np.array(bounding_box_coords[0]) - np.array(bounding_box_coords[1]))
        self.parse_regions(eta=diagonal_length)
        self.bounding_box = box(bounding_box_coords[0][0], bounding_box_coords[0][1],
                                bounding_box_coords[1][0], bounding_box_coords[1][1])

    def compute_ridges_coords(self):
        """Computes the coordinates of the voronoi ridges. It uses the midpoint and the ridge vertex as vector basis. If
        the ridge vertex is not in the convex hull, then we reverse the vector direction so that the cell has the right
        shape."""
        self.ridges_coords = {}
        for p1, p2 in self.voronoi_obj.ridge_dict:
            ridge_vertices = self.voronoi_obj.ridge_dict[(p1, p2)]
            if ridge_vertices[0] < 0 <= ridge_vertices[1]:
                c1 = self.voronoi_obj.vertices[ridge_vertices[1]]
                c2 = (self.voronoi_obj.points[p1] + self.voronoi_obj.points[p2]) / 2.0
            elif ridge_vertices[1] < 0 <= ridge_vertices[0]:
                c1 = self.voronoi_obj.vertices[ridge_vertices[0]]
                c2 = (self.voronoi_obj.points[p1] + self.voronoi_obj.points[p2]) / 2.0
            else:
                continue
            ridge_coords = c2 - c1
            if not self.hull_polygon.intersects(Point(c1)):
                ridge_coords *= -1
            ridge_coords /= np.linalg.norm(ridge_coords)
            self.ridges_coords[(p1, p2)] = ridge_coords

    def parse_regions(self, eta=1.0):
        """Parsing of the voronoi regions using the coordinates of the voronoi ridges. It sets an extremity point at
        infinity (represented by eta) along the ridge. In case of duplicate points, one of the cell will be empty and
        the other won't be."""
        nb_points = len(self.voronoi_obj.points)
        self.all_regions_coords = []
        for p in range(nb_points):
            region = self.voronoi_obj.regions[self.voronoi_obj.point_region[p]]
            region_coords = []
            for ix in range(len(region)):
                v1 = region[ix]
                if v1 >= 0:
                    region_coords.append([self.voronoi_obj.vertices[v1][0], self.voronoi_obj.vertices[v1][1]])
                    continue
                if (ix + 1) < len(region):
                    v2 = region[ix + 1]
                else:
                    v2 = region[0]
                if (ix - 1) >= 0:
                    v0 = region[ix - 1]
                else:
                    v0 = region[-1]
                if v0 != v2:
                    first_ridge_candidates = [(p1, p2) for (p1, p2), vs in self.voronoi_obj.ridge_dict.items()
                                              if (p in (p1, p2)) and (vs == [v0, -1] or vs == [-1, v0])]
                    second_ridge_candidates = [(p1, p2) for (p1, p2), vs in self.voronoi_obj.ridge_dict.items()
                                              if (p in (p1, p2)) and (vs == [v2, -1] or vs == [-1, v2])]
                    if len(first_ridge_candidates) == 0 or len(second_ridge_candidates) == 0:
                        # It means there is a duplicate in points
                        region_coords = []  # This point region will be empty, but the duplicate region won't.
                        break
                    first_ridge = first_ridge_candidates[0]
                    second_ridge = second_ridge_candidates[0]
                else:
                    matching_ridges = [(p1, p2) for p1, p2 in self.voronoi_obj.ridge_dict if (p1 == p or p2 == p) and
                                       (self.voronoi_obj.ridge_dict[(p1, p2)] == [v0, -1] or
                                        self.voronoi_obj.ridge_dict[(p1, p2)] == [-1, v0])]
                    first_ridge = matching_ridges[0]
                    second_ridge = matching_ridges[1]
                first_interpolated_coord = self.voronoi_obj.vertices[v0] + self.ridges_coords[first_ridge] * eta
                second_interpolated_coord = self.voronoi_obj.vertices[v2] + self.ridges_coords[second_ridge] * eta
                region_coords.append([first_interpolated_coord[0], first_interpolated_coord[1]])
                region_coords.append([second_interpolated_coord[0], second_interpolated_coord[1]])
            self.all_regions_coords.append(np.array(region_coords))

    def get_regions_as_polygons(self) -> list:
        """Collection of all the voronoi cells coordinates and creation of shapely polygon with a bounding box trimming
        step."""
        all_polygons = []
        for region in self.all_regions_coords:
            if len(region) > 0:
                polygon = Polygon(region)
                trimmed_polygon = polygon.intersection(self.bounding_box)
                all_polygons.append(trimmed_polygon)
            else:
                all_polygons.append(Polygon())
        return all_polygons

    def get_regions_as_gdf(self, crs=None) -> gpd.GeoDataFrame:
        """Collect all the voronoi cells as shapely polygons and return them as a GeoDataFrame."""
        voronoi_cells_gdf = gpd.GeoDataFrame(columns=['PointId', 'geometry'], crs=crs)
        all_polygons = self.get_regions_as_polygons()
        for point_id, polygon in enumerate(all_polygons):
            voronoi_cells_gdf.loc[len(voronoi_cells_gdf)] = [point_id, polygon]
        return voronoi_cells_gdf


import pyvoronoi
from shapely.geometry import LineString
from shapely.ops import split, linemerge

class PyVoronoiHelper:
    """Add-on for the pyvoronoi (boost voronoi) tool. It computes the voronoi cells within a bounding box."""

    def __init__(self, points: list, segments: list, bounding_box_coords: list, scaling_factor=10000,
                 discretization_tolerance=0.05):
        self.pv = pyvoronoi.Pyvoronoi(scaling_factor)
        for p in points:
            self.pv.AddPoint(p)
        for s in segments:
            self.pv.AddSegment(s)
        points_and_lines = points + [p for l in segments for p in l]
        self.convex_hull = MultiPoint(points_and_lines).convex_hull
        self.pv.Construct()
        self.discretization_tolerance = discretization_tolerance
        self.bounding_box_coords = bounding_box_coords

    # TODO: map input lines with their sublines, do union of polygons in output

    @staticmethod
    def split_linestring_as_simple_linestrings(line: GenericLine) -> list:
        """Split a linestring if it is not simple (i.e. it crosses itself)."""
        if not line.is_simple:
            mls = line.intersection(line)
            if line.geom_type == 'LineString' and mls.geom_type == 'MultiLineString':
                mls = linemerge(mls)
            return list(mls)
        else:
            return [line]

    @staticmethod
    def split_as_simple_segments(lines: list, tol=1e-6) -> dict:
        from collections import defaultdict
        split_lines = defaultdict(list)
        all_split_lines = PyVoronoiHelper.split_linestring_as_simple_linestrings(MultiLineString(lines))
        lines_stack = lines.copy()
        for sub_line in all_split_lines:
            for i, line in enumerate(lines_stack):
                if line.buffer(tol, 1).contains(sub_line):
                    split_lines[i].append(sub_line)
                    del lines_stack[i]
                    lines_stack.insert(0, line)
                    break
        return split_lines


    @staticmethod
    def split_intersected_linestrings(lines: list) -> dict:
        """Split a list of linestrings to a list of non crossing lines."""
        split_lines = {i: [l] for i, l in enumerate(lines)}
        # Make simple one by one (self intersection)
        # TODO
        # Split intersections
        treated_lines = set()
        treated_couples = set()
        while True:
            to_break = False
            for i1, sub_lines1 in split_lines.items():
                if i1 in treated_lines:
                    continue
                mls1 = MultiLineString(sub_lines1)
                for i2, sub_lines2 in split_lines.items():
                    if i1 != i2 and (i1, i2) not in treated_couples:
                        mls2 = MultiLineString(sub_lines2)
                        if mls1.intersects(mls2):
                            new_sub_lines1, new_sub_lines2 = PyVoronoiHelper.split_linestrings_at_intersection(mls1, mls2)
                            if len(new_sub_lines1) != 1:
                                split_lines[i1] = PyVoronoiHelper.get_as_list_of_linestrings(new_sub_lines1)
                                to_break = True
                            if len(new_sub_lines2) != 1:
                                split_lines[i2] = PyVoronoiHelper.get_as_list_of_linestrings(new_sub_lines2)
                                to_break = True
                            treated_couples.add((i1, i2))
                            if to_break:
                                print("found", i1, i2)
                                break
                if to_break:
                    break
                else:
                    print("treated", i1)
                    treated_lines.add(i1)
                    treated_couples = set()
            if not to_break:
                break
        return split_lines
        #lines_as_multilinestring = MultiLineString(lines)
        #return self.split_linestring_as_simple_linestrings(lines_as_multilinestring)

    @staticmethod
    def get_as_list_of_linestrings(obj:list) -> list:
        grown_obj = []
        for i in obj:
            if isinstance(i, MultiLineString):
                grown_obj.extend(list(i))
            else:
                grown_obj.append(i)
        return grown_obj



    @staticmethod
    def split_linestrings_at_intersection(line1: GenericLine, line2: GenericLine) -> tuple:
        """Split two linestrings at their intersection point(s). Returns two geometry collections containing the set of
        split linestrings."""
        intersection = line1.intersection(line2)
        if isinstance(intersection, (Point, MultiPoint)):
            line1_split = PyVoronoiHelper.split(line1, intersection)
            line2_split = PyVoronoiHelper.split(line2, intersection)
        elif isinstance(intersection, (LineString, MultiLineString)):
            line1_split = line1.difference(intersection)
            line2_split = line2
        else:
            line1_split = []  # It can happen if the lines intersects at a point and at a line
            line2_split = line2
        return (line1_split, line2_split)

    @staticmethod
    def split_linestring(line: LineString) -> list:
        """Split a linestring into a list of segments (trivial linestring)."""
        split_lines = []
        for i in range(len(line.coords) - 1):
            split_lines.append(LineString([line.coords[i], line.coords[i + 1]]))
        return split_lines

    @staticmethod
    def split(line: GenericLine, points: Union[Point, MultiPoint]) -> list:
        if isinstance(line, LineString):
            cut = PyVoronoiHelper.cut
        else:
            cut = PyVoronoiHelper.cut_multilinestring
        if isinstance(points, Point):
            distance = line.project(points)
            return cut(line, distance)
        else:
            current_line = line
            split_lines = []
            distances = [(line.project(p), p) for p in points]
            sorted_distances = sorted(distances, key=lambda x: x[0])
            cut_result = None
            for d, p in sorted_distances:
                if d <= 0 or d >= line.length:
                    continue
                cut_result = cut(current_line, current_line.project(p))
                split_lines.append(cut_result[0])
                current_line = cut_result[1]
            if cut_result is None:
                return [line]
            else:
                split_lines.append(cut_result[1])
                return split_lines

    @staticmethod
    def cut_multilinestring(line: MultiLineString, distance: float) -> list:
        # Cuts a line in two at a distance from its starting point
        if distance <= 0.0 or distance >= line.length:
            return [line]
        length_counter = 0.0
        for l, sub_line in enumerate(line):
            line_length = sub_line.length
            length_counter += line_length
            if distance > length_counter:
                continue
            coords = list(sub_line.coords)
            for i, p in enumerate(coords):
                pd = line.project(Point(p))
                if pd == distance:
                    return [line[:(l + 1)], line[l:]]
                if pd > distance:
                    cp = line.interpolate(distance)
                    first_cut_part = LineString(coords[:i] + [(cp.x, cp.y)])
                    second_cut_part = LineString([(cp.x, cp.y)] + coords[i:])
                    first_part = MultiLineString(list(line[:l]) + [first_cut_part])
                    second_part = MultiLineString([second_cut_part] + list(line[(l+1):]))
                    return [first_part, second_part]

    @staticmethod
    def cut(line: LineString, distance: float) -> list:
        # Cuts a line in two at a distance from its starting point
        if distance <= 0.0 or distance >= line.length:
            return [line]
        coords = list(line.coords)
        for i, p in enumerate(coords):
            pd = line.project(Point(p))
            if pd == distance:
                return [
                    LineString(coords[:i + 1]),
                    LineString(coords[i:])]
            if pd > distance:
                cp = line.interpolate(distance)
                return [
                    LineString(coords[:i] + [(cp.x, cp.y)]),
                    LineString([(cp.x, cp.y)] + coords[i:])]

    def get_cells_as_gdf(self) -> gpd.GeoDataFrame:
        gdf = gpd.GeoDataFrame(columns=["id", "geometry"])
        cells_geometries = self.get_cells_as_polygons()
        gdf["geometry"] = list(cells_geometries.values())
        gdf["id"] = list(cells_geometries.keys())
        return gdf

    def get_cells_as_polygons(self) -> dict:
        diagonal_length = np.linalg.norm(np.array(self.bounding_box_coords[0]) - np.array(self.bounding_box_coords[1]))
        cells_coordinates = self.get_cells_coordiates(eta=diagonal_length,
                                                      discretization_tolerance=self.discretization_tolerance)
        bounding_box = box(self.bounding_box_coords[0][0], self.bounding_box_coords[0][1],
                           self.bounding_box_coords[1][0], self.bounding_box_coords[1][1])
        cells_as_polygons = dict()
        for i, coords in cells_coordinates.items():
            if len(coords) > 2:
                polygon = Polygon(coords)
                trimmed_polygon = polygon.intersection(bounding_box)
                cells_as_polygons[i] = trimmed_polygon
        return cells_as_polygons

    def get_cells_coordiates(self, eta=1.0, discretization_tolerance=0.05) -> dict:
        vertices = self.pv.GetVertices()
        cells = self.pv.GetCells()
        edges = self.pv.GetEdges()
        cells_coordinates = dict()
        for c in cells:
            cell_coords = []
            for e in c.edges:
                edge = edges[e]
                start_vertex = vertices[edge.start]
                end_vertex = vertices[edge.end]
                if edge.is_linear:
                    if edge.start != -1 and edge.end != -1:
                        self.add_polygon_coordinates(cell_coords, [start_vertex.X, start_vertex.Y])
                        self.add_polygon_coordinates(cell_coords, [end_vertex.X, end_vertex.Y])
                    else:
                        start_is_infinite = edge.start == -1
                        if start_is_infinite:
                            ridge_vertex = end_vertex
                        else:
                            ridge_vertex = start_vertex
                        ridge_point = np.array([ridge_vertex.X, ridge_vertex.Y])
                        twin_cell = cells[edges[edge.twin].cell]
                        if c .site == twin_cell.site:
                            if c.source_category == 3:
                                 segment = np.array(self.pv.RetriveScaledSegment(cells[edge.cell]))
                                 if start_is_infinite:
                                     second_point = segment[1]
                                     ridge_direction = second_point - ridge_point
                                     if np.linalg.norm(ridge_direction) == 0.0:
                                         ridge_direction = - self.get_orthogonal_direction(segment[1] - segment[0])
                                 else:
                                     first_point = segment[0]
                                     ridge_direction = first_point - ridge_point
                                     if np.linalg.norm(ridge_direction) == 0.0:
                                         ridge_direction = - self.get_orthogonal_direction(segment[1] - segment[0])
                            else:
                                first_point = self.pv.RetrieveScaledPoint(c)
                                ridge_direction = first_point - ridge_point
                                if np.linalg.norm(ridge_direction) == 0.0:
                                    segment = np.array(self.pv.RetriveScaledSegment(c))
                                    ridge_direction = - self.get_orthogonal_direction(segment[1] - segment[0])
                        else:
                            first_point = self.pv.RetrieveScaledPoint(c)
                            second_point = self.pv.RetrieveScaledPoint(twin_cell)
                            midpoint = np.array([(first_point[0] + second_point[0]) / 2.0,
                                                 (first_point[1] + second_point[1]) / 2.0])
                            ridge_direction = ridge_point - midpoint
                            if self.convex_hull.intersects(Point(ridge_point)):
                                ridge_direction *= -1
                        ridge_direction_norm = np.linalg.norm(ridge_direction)
                        if ridge_direction_norm != 0.0:
                            ridge_direction /= ridge_direction_norm
                        ridge_limit_point = ridge_point + ridge_direction * eta
                        if start_is_infinite:
                            self.add_polygon_coordinates(cell_coords, [ridge_limit_point[0], ridge_limit_point[1]])
                            self.add_polygon_coordinates(cell_coords, [ridge_vertex.X, ridge_vertex.Y])
                        else:
                            self.add_polygon_coordinates(cell_coords, [ridge_vertex.X, ridge_vertex.Y])
                            self.add_polygon_coordinates(cell_coords, [ridge_limit_point[0], ridge_limit_point[1]])
                else:
                    for p in self.pv.DiscretizeCurvedEdge(e, discretization_tolerance):
                        cell_coords.append(p)
            cells_coordinates[c.cell_identifier] = cell_coords
        return cells_coordinates

    @staticmethod
    def get_orthogonal_direction(dir: np.array) -> np.array:
        if dir[1] == 0.0:
            return np.array([0.0, 1.0])
        return np.array([1.0, - dir[0] / dir[1]])

    @staticmethod
    def add_polygon_coordinates(coordinates: list, point: list):
        if coordinates:
            last_point = coordinates[-1]
            if last_point[0] == point[0] and last_point[1] == point[1]:
                return
        coordinates.append(point)


if __name__ == "__main__":

    import geopandas as gpd


    import numpy as np
    from shapely.geometry import *


    points = [[0.1, 1.0], [0.8, 0.8], [0.5, 0.3]]

    lines = [[[0.1,0.8],[0.3,0.6]],
    [[0.3,0.6],[0.4,0.6]],
    [[0.4,0.6],[0.4,0.5]],
    [[0.4,0.6],[0.4,0.7]],
    [[0.4,0.7],[0.5,0.8]],
    [[0.4,0.7],[0.5,0.6]],
    [[0.5,0.6],[0.7,0.7]],
    [[0.2, 0.3], [0.5, 0.3]]]

    path = r"C:\Users\hchareyre\Documents\trash\Nouveau dossier (5)"

    lines_df = gpd.GeoDataFrame(columns=["geometry"])
    for l in lines:
        lines_df.loc[len(lines_df)] = [LineString(l)]
    lines_df.to_file(path + r"\lines.shp")

    points_df = gpd.GeoDataFrame(columns=["geometry"])
    for p in points:
        points_df.loc[len(points_df)] = [Point(p)]
    points_df.to_file(path + r"\points.shp")

    points_and_lines = points + [p for l in lines for p in l]


    convex_hull = MultiPoint(points_and_lines).convex_hull

    convex_hull = convex_hull.buffer(1/100.0)
    convex_hull.to_wkt()

    self = PyVoronoiHelper(points, lines, [[-2, -2], [2, 2]])


    gdf= self.get_cells_as_gdf()
    gdf.drop(index=[i for i in gdf.index if isinstance(gdf.at[i, "geometry"], GeometryCollection)], inplace=True)
    gdf.to_file(path + r"\test22.shp")
