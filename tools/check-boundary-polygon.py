#!/usr/bin/env python3
#-*- coding: utf-8 -*-

###########################################################################
##                                                                       ##
## Copyrights Rodrigo Frédéric 2014                                      ##
##                                                                       ##
## This program is free software: you can redistribute it and/or modify  ##
## it under the terms of the GNU General Public License as published by  ##
## the Free Software Foundation, either version 3 of the License, or     ##
## (at your option) any later version.                                   ##
##                                                                       ##
## This program is distributed in the hope that it will be useful,       ##
## but WITHOUT ANY WARRANTY; without even the implied warranty of        ##
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         ##
## GNU General Public License for more details.                          ##
##                                                                       ##
## You should have received a copy of the GNU General Public License     ##
## along with this program.  If not, see <http://www.gnu.org/licenses/>. ##
##                                                                       ##
###########################################################################

import json
import os
import sys
import logging
import pyproj
import shapefile

logger = logging.getLogger('shapely.geos')
logging_handler_out = logging.StreamHandler(sys.stdout)
logger.addHandler(logging_handler_out)
logger.setLevel(logging.INFO)

import shapely.geometry
import shapely.ops
import shapely.wkt
from shapely.geometry import MultiPolygon

sys.path.append("..")

from modules import IssuesFile_PolygonFilter
from modules import downloader

import modules.config
import osmose_config as config

landuse = "https://osmdata.openstreetmap.de/download/simplified-land-polygons-complete-3857.zip"


# Function based on http://wiki.openstreetmap.org/wiki/Osmosis/Polygon_Filter_File_Python_Parsing
def parse_poly(lines):
    """ Parse an Osmosis polygon filter file.
        Accept a sequence of lines from a polygon file, return a shapely.geometry.MultiPolygon object.
        http://wiki.openstreetmap.org/wiki/Osmosis/Polygon_Filter_File_Format
    """
    in_ring = False
    coords = []

    for (index, line) in enumerate(lines):
        if index == 0:
            # first line is junk.
            continue

        elif index == 1:
            # second line is the first polygon ring.
            coords.append([[], []])
            ring = coords[-1][0]
            in_ring = True

        elif in_ring and line.strip() == 'END':
            # we are at the end of a ring, perhaps with more to come.
            in_ring = False

        elif in_ring:
            # we are in a ring and picking up new coordinates.
            ring.append(list(map(float, line.split())))

        elif not in_ring and line.strip() == 'END':
            # we are at the end of the whole polygon.
            break

        elif not in_ring and line.startswith('!'):
            # we are at the start of a polygon part hole.
            coords[-1][1].append([])
            ring = coords[-1][1][-1]
            in_ring = True

        elif not in_ring:
            # we are at the start of a polygon part.
            coords.append([[], []])
            ring = coords[-1][0]
            in_ring = True

    return MultiPolygon(coords)


def load_poly(poly):
    try:
        #print(poly)
        s = downloader.urlread(poly, 1)
        return parse_poly(s.split('\n'))
    except IOError as e:
        print(e)
        return

def iter_countries(options):

    all_polys = []
    c = 0 
 
    for country, country_conf in config.config.items():
        if not country_conf.polygon_id:
            print("Warning(%s): no polygon_id" % country)
            continue
        if not 'poly' in country_conf.download:
            print("Warning(%s): no poly declared" % country)
            continue
        if c > 20:
            break
        c += 1
        if options.check:
            #print("%s" % country)
            poly = load_poly(country_conf.download['poly'])
            if not poly:
                print("Warning(%s): no poly fetched : %s" % (country, country_conf.download['poly']))
            else:
                polygonFilter = IssuesFile_PolygonFilter.PolygonFilter(country_conf.polygon_id, cache_delay=1)
                if not polygonFilter.pip.polygon.polygon.is_valid:
                    print("Error(%s) boundary not valid (r_id=%s)" % (country, country_conf.polygon_id))
                if not poly.is_valid:
                    print("Error(%s) poly not valid (r_id=%s)" % (country, country_conf.polygon_id))
                try:
                    if not poly.contains(polygonFilter.pip.polygon.polygon):
                        print("Error(%s) poly inside boundary (r_id=%s, poly=%s)" % (country, country_conf.polygon_id, country_conf.download['poly']))
                except:
                    print("Error(%s) evaluating intersection (r_id=%s, poly=%s)" % (country, country_conf.polygon_id, country_conf.download['poly']))

        if options.union:
            polygonFilter = IssuesFile_PolygonFilter.PolygonFilter(country_conf.polygon_id)
            all_polys.append(polygonFilter.pip.polygon.polygon)

    return all_polys

def union_countries(options, union_poly_file, all_polys):

    print("Number of original countries/regions:", len(all_polys))
    print("union start")
    union_poly = shapely.ops.unary_union(all_polys)
    print("union stop")
    print("Number of polygons after union:", len(union_poly))

    with open(union_poly_file, "w") as f:
        f.write(json.dumps(shapely.geometry.mapping(union_poly), indent=1))

def diff_landuse(options, union_poly_file):

    shp_file = os.path.join(modules.config.dir_cache, "landuse_shp.zip")

    with open(union_poly_file, "r") as f:
        union_poly = shapely.geometry.shape(json.load(f))

    try:
        os.link(downloader.path(landuse, delay=31), shp_file)
    except:
        pass
    print(shp_file)
    shp = shapefile.Reader(shp_file)
    print(shp)

    proj_orig = pyproj.CRS('EPSG:3857')
    proj_dest = pyproj.CRS('EPSG:4326')
    project = pyproj.Transformer.from_crs(proj_orig, proj_dest, always_xy=True).transform

    print("starting check")
    all_landuse_polys = []

    for s in shp.shapes():
      all_landuse_polys.append(shapely.ops.transform(project, shapely.geometry.shape(s)))

    print("Number of original countries/regions:", len(all_landuse_polys))
    print("union start")
    landuse_poly = shapely.ops.unary_union(all_landuse_polys)
    print("union stop")
    print("Number of polygons after union:", len(landuse_poly))

    diff_poly = landuse_poly.difference(union_poly)
    print(diff_poly.area)
   
    diff_poly_file = "diff_poly.geojson"

    with open(diff_poly_file, "w") as f:
        f.write(json.dumps(shapely.geometry.mapping(diff_poly), indent=1))

def main(options):

    if not os.path.exists(modules.config.dir_cache):
        os.makedirs(modules.config.dir_cache)

    union_poly_file = "union_poly.geojson"

    if options.check or options.union:
        all_polys = iter_countries(options)

    if options.union:
        union_countries(options, union_poly_file, all_polys)

    if options.diff_landuse:
        diff_landuse(options, union_poly_file)


if __name__ == "__main__":
    #=====================================
    # analyse of parameters

    from optparse import OptionParser

    parser = OptionParser()
    parser.add_option("--check", dest="check", action="store_true",
                      help="Disable checking of polygons")

    parser.add_option("--union", dest="union", action="store_true",
                      help="Union of all polygons")

    parser.add_option("--diff-landuse", dest="diff_landuse", action="store_true",
                      help="Generate a diff of Union of all polygons and OSM's landuse")

    (options, args) = parser.parse_args()

    if not options.check and not options.union and not options.diff_landuse:
        parser.print_help()
        sys.exit(1)

    main(options)
