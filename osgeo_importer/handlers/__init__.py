import requests
from django import db
from django.conf import settings
from osgeo_importer.inspectors import OGRFieldConverter


DEFAULT_IMPORT_HANDLERS = ['osgeo_importer.handlers.FieldConverterHandler',
                           'osgeo_importer.handlers.geoserver.GeoserverPublishHandler',
                           'osgeo_importer.handlers.geoserver.GeoserverPublishCoverageHandler',
                           'osgeo_importer.handlers.geoserver.GeoServerTimeHandler',
                           'osgeo_importer.handlers.geoserver.GeoWebCacheHandler',
                           'osgeo_importer.handlers.geoserver.GeoServerBoundsHandler',
                           'osgeo_importer.handlers.geonode.GeoNodePublishHandler']

IMPORT_HANDLERS = getattr(settings, 'IMPORT_HANDLERS', DEFAULT_IMPORT_HANDLERS)


def ensure_can_run(func):
    """
    Convenience decorator that executes the "can_run" method class and returns the function if the can_run is True.
    """

    def func_wrapper(self, *args, **kwargs):

        if self.can_run(*args, **kwargs):
            return func(self, *args, **kwargs)

    return func_wrapper


class ImportHandler(object):
    """
    A mixin providing the basic layout for handlers.
    """
    def __init__(self, importer, *args, **kwargs):
        self.importer = importer

    @ensure_can_run
    def handle(self, layer, layerconfig, *args, **kwargs):
        """
        This method is executed by each Importer.

        :param layer: The name of the imported layer.
        :param layerconfig: The configuration options of the layer (dict).
        """
        raise NotImplementedError('Subclass should implement this.')

    def can_run(self, layer, layer_config, *args, **kwargs):
        """
        Returns True if the handler has enough information to execute.
        """
        return True


class FieldConverterHandler(ImportHandler):
    """
    Converts fields based on the layer_configuration.
    """

    def convert_field_to_time(self, layer, field):
        d = db.connections['datastore'].settings_dict
        connection_string = "PG:dbname='%s' user='%s' password='%s' host='%s' port='%s'" % (d['NAME'], d['USER'],
                                                                        d['PASSWORD'], d['HOST'], d['PORT'])

        with OGRFieldConverter(connection_string) as datasource:
            return datasource.convert_field(layer, field)

    @ensure_can_run
    def handle(self, layer, layer_config, *args, **kwargs):
        try:
            for field_to_convert in set(layer_config.get('convert_to_date', [])):

                if not field_to_convert:
                    continue

                xd_col = self.convert_field_to_time(layer, field_to_convert)

                # if the start_date or end_date needed to be converted to a date
                # field, use the newly created field name
                for date_option in ('start_date', 'end_date'):
                    if layer_config.get(date_option) == field_to_convert:
                        layer_config[date_option] = xd_col.lower()
        except Exception as e:
            print "Error: %s"%(e)
