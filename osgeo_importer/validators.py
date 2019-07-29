import logging
import os
from zipfile import is_zipfile, ZipFile

from django.conf import settings

from osgeo_importer.importers import VALID_EXTENSIONS
from osgeo_importer.utils import NoDataSourceFound, load_handler


OSGEO_IMPORTER = getattr(settings, 'OSGEO_IMPORTER', 'osgeo_importer.importers.OGRImport')

logger = logging.getLogger(__name__)

NONDATA_EXTENSIONS = ['shx', 'prj', 'dbf', 'xml', 'sld', 'cpg']

ALL_OK_EXTENSIONS = set(VALID_EXTENSIONS) | set(NONDATA_EXTENSIONS)


def valid_file(file):
    """ Returns an empty list if file is valid, or a list of strings describing problems with the file.
        @see VALID_EXTENSIONS, NONDATA_EXTENSIONS
    """
    errors = []
    basename = os.path.basename(file.name)
    _, extension = os.path.splitext(basename)
    extension = extension.lstrip('.').lower()

    if is_zipfile(file):
        with ZipFile(file) as zip:
            for content_name in zip.namelist():
                content_file = zip.open(content_name)
                content_errors = valid_file(content_file)
                # This does not work right...
                #if not content_errors:
                #    errors.extend(content_errors)
    elif extension not in ALL_OK_EXTENSIONS:
        errors.append(
            '{}: "{}" not found in VALID_EXTENSIONS, NONDATA_EXTENSIONS'.format(basename, extension)
        )

    return errors


# DONE
def valid_file2(file):
    """ Returns an empty list if file is valid,
        or a list of strings describing problems with the file.
        @see VALID_EXTENSIONS, NONDATA_EXTENSIONS
    """
    basename = os.path.basename(file.name)
    _, extension = os.path.splitext(basename)
    extension = extension.lstrip('.').lower()

    if extension not in ALL_OK_EXTENSIONS:
        return '{0}: "{1}" not found in VALID_EXTENSIONS, ' \
               'NONDATA_EXTENSIONS'.format(basename, extension)

    return None


def validate_shapefiles_have_all_parts(filenamelist):
    shp = []
    prj = []
    dbf = []
    shx = []
    for file in filenamelist:
        base, extension = os.path.splitext(file)
        extension = extension.lstrip('.').lower()
        if extension == 'shp':
            shp.append(base)
        elif extension == 'prj':
            prj.append(base)
        elif extension == 'dbf':
            dbf.append(base)
        elif extension == 'shx':
            shx.append(base)
    if set(shp) == set(prj) == set(dbf) == set(shx):
        return True
    else:
        return False


# DONE
def validate_shapefiles_have_all_parts2(files):
    shp = []
    prj = []
    dbf = []
    shx = []
    shape_files = set()
    for file in files:
        base, extension = os.path.splitext(file.name)
        extension = extension.lstrip('.').lower()
        if extension == 'shp':
            shape_files.add(base)
            shp.append(base)
        elif extension == 'prj':
            shape_files.add(base)
            prj.append(base)
        elif extension == 'dbf':
            shape_files.add(base)
            dbf.append(base)
        elif extension == 'shx':
            shape_files.add(base)
            shx.append(base)
    if set(shp) == set(prj) == set(dbf) == set(shx):
        return None
    else:
        bad_files = []
        for shpf in shape_files:
            if shpf not in shp or shpf not in prj or shpf not in dbf or \
                    shpf not in shx:
                bad_files.append(shpf)
        return bad_files


# DONE
def validate_inspector_can_read(filename):
    filedir, file = os.path.split(filename)
    base, extension = os.path.splitext(file)
    extension = extension.lstrip('.').lower()
    if extension in NONDATA_EXTENSIONS:
        return True
    try:
        importer = load_handler(OSGEO_IMPORTER, filename)
        data, inspector = importer.open_source_datastore(filename)
        # Ensure the data has a geometry.
        for description in inspector.describe_fields():
            if description.get('raster') is False and description.get('geom_type') in inspector.INVALID_GEOMETRY_TYPES:
                return False
    except NoDataSourceFound:
        return False
    # Happens when there is bad data such as a zip file that got passed in
    except RuntimeError:
        return False
    return True
