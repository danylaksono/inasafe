# coding=utf-8
"""
InaSAFE Disaster risk assessment tool developed by AusAid -
  **IS Utilities implementation.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""
from PyQt4.QtNetwork import QNetworkRequest, QNetworkReply

__author__ = 'tim@linfiniti.com'
__revision__ = '$Format:%H$'
__date__ = '29/01/2011'
__copyright__ = 'Copyright 2012, Australia Indonesia Facility for '
__copyright__ += 'Disaster Reduction'

import os
import sys
import traceback
import logging
import uuid

from PyQt4 import QtCore, QtGui
from PyQt4.QtCore import QCoreApplication, QFile, QUrl

from qgis.core import (
    QGis,
    QgsRasterLayer,
    QgsMapLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsVectorLayer)

from safe_qgis.exceptions import MemoryLayerCreationError

from safe_qgis.safe_interface import (
    ErrorMessage,
    DEFAULTS,
    safeTr,
    get_version,
    messaging as m)
from safe_qgis.safe_interface import styles
INFO_STYLE = styles.INFO_STYLE

#do not remove this even if it is marked as unused by your IDE
#resources are used by html footer and header the comment will mark it unused
#for pylint
# noinspection PyUnresolvedReferences
from safe_qgis.ui import resources_rc  # pylint: disable=W0611

LOGGER = logging.getLogger('InaSAFE')


def tr(theText):
    """We define a tr() alias here since the utilities implementation below
    is not a class and does not inherit from QObject.
    .. note:: see http://tinyurl.com/pyqt-differences

    :param theText: String to be translated
    :type theText: str

    :returns: Translated version of the given string if available, otherwise
        the original string.
    :rtype: str
    """
    # noinspection PyCallByClass,PyTypeChecker,PyArgumentList
    return QCoreApplication.translate('@default', theText)


def get_error_message(exception, context=None, suggestion=None):
    """Convert exception into an ErrorMessage containing a stack trace.


    :param exception: Exception object.
    :type exception: Exception

    :param context: Optional context message.
    :type context: str

    :param suggestion: Optional suggestion.
    :type suggestion: str

    .. see also:: https://github.com/AIFDR/inasafe/issues/577

    :returns: An error message with stack trace info suitable for display.
    :rtype: ErrorMessage
    """

    myTraceback = ''.join(traceback.format_tb(sys.exc_info()[2]))

    myProblem = m.Message(m.Text(exception.__class__.__name__))

    if str(exception) is None or str(exception) == '':
        myProblem.append = m.Text(tr('No details provided'))
    else:
        myProblem.append = m.Text(str(exception))

    mySuggestion = suggestion
    if mySuggestion is None and hasattr(exception, 'suggestion'):
        mySuggestion = exception.message

    myErrorMessage = ErrorMessage(
        myProblem,
        detail=context,
        suggestion=mySuggestion,
        traceback=myTraceback
    )

    myArgs = exception.args
    for myArg in myArgs:
        myErrorMessage.details.append(myArg)

    return myErrorMessage


def getWGS84resolution(layer):
    """Return resolution of raster layer in EPSG:4326.

    If input layer is already in EPSG:4326, simply return the resolution
    If not, work it out based on EPSG:4326 representations of its extent.

    :param layer: Raster layer
    :type layer: QgsRasterLayer or QgsMapLayer

    :returns: The resolution of the given layer.
    :rtype: float

    """

    msg = tr(
        'Input layer to getWGS84resolution must be a raster layer. '
        'I got: %s' % str(layer.type())[1:-1])
    if not layer.type() == QgsMapLayer.RasterLayer:
        raise RuntimeError(msg)

    if layer.crs().authid() == 'EPSG:4326':
        myCellSize = layer.rasterUnitsPerPixelX()

    else:
        # Otherwise, work it out based on EPSG:4326 representations of
        # its extent

        # Reproject extent to EPSG:4326
        myGeoCrs = QgsCoordinateReferenceSystem()
        myGeoCrs.createFromSrid(4326)
        myXForm = QgsCoordinateTransform(layer.crs(), myGeoCrs)
        myExtent = layer.extent()
        myProjectedExtent = myXForm.transformBoundingBox(myExtent)

        # Estimate cell size
        myColumns = layer.width()
        myGeoWidth = abs(myProjectedExtent.xMaximum() -
                         myProjectedExtent.xMinimum())
        myCellSize = myGeoWidth / myColumns

    return myCellSize


def html_header():
    """Get a standard html header for wrapping content in.

    :returns: A header containing a web page preamble in html - up to and
        including the body open tag.
    :rtype: str
    """
    myFile = QtCore.QFile(':/plugins/inasafe/header.html')
    if not myFile.open(QtCore.QIODevice.ReadOnly):
        return '----'
    myStream = QtCore.QTextStream(myFile)
    myHeader = myStream.readAll()
    myFile.close()
    return myHeader


def html_footer():
    """Get a standard html footer for wrapping content in.

    :returns: A header containing a web page closing content in html - up to
        and including the body close tag.
    :rtype: str
    """
    myFile = QtCore.QFile(':/plugins/inasafe/footer.html')
    if not myFile.open(QtCore.QIODevice.ReadOnly):
        return '----'
    myStream = QtCore.QTextStream(myFile)
    myFooter = myStream.readAll()
    myFile.close()
    return myFooter


def qgis_version():
    """Get the version of QGIS.

    :returns: QGIS Version where 10700 represents QGIS 1.7 etc.
    :rtype: int
    """
    myVersion = unicode(QGis.QGIS_VERSION_INT)
    myVersion = int(myVersion)
    return myVersion


def layer_attribute_names(layer, allowed_types, current_keyword=None):
    """Iterates over the layer and returns int or string fields.

    :param layer: A vector layer whose attributes shall be returned.
    :type layer: QgsVectorLayer

    :param allowed_types: List of QVariant that are acceptable for the
        attribute. e.g.: [QtCore.QVariant.Int, QtCore.QVariant.String].
    :type allowed_types: list(QVariant)

    :param current_keyword: The currently stored keyword for the attribute.
    :type current_keyword: str

    :returns: A two-tuple containing all the attribute names of attributes
        that have int or string as field type (first element) and the position
        of the current_keyword in the attribute names list, this is None if
        current_keyword is not in the list of attributes (second element).
    :rtype: tuple(list(str), int)
    """

    if layer.type() == QgsMapLayer.VectorLayer:
        myProvider = layer.dataProvider()
        myProvider = myProvider.fields()
        myFields = []
        mySelectedIndex = None
        i = 0
        for f in myProvider:
            # show only int or string myFields to be chosen as aggregation
            # attribute other possible would be float
            if f.type() in allowed_types:
                myCurrentFieldName = f.name()
                myFields.append(myCurrentFieldName)
                if current_keyword == myCurrentFieldName:
                    mySelectedIndex = i
                i += 1
        return myFields, mySelectedIndex
    else:
        return None, None


def breakdown_defaults(theDefault=None):
    """Get a dictionary of default values to be used for post processing.

    .. note: This method takes the DEFAULTS from safe and modifies them
        according to user preferences defined in QSettings.

    :param theDefault: A key of the defaults dictionary. Use this to
        optionally retrieve only a specific default.
    :type theDefault: str

    :returns: A dictionary of defaults values to be used or the default
        value if a key is passed. None if the requested default value is not
        valid.
    :rtype: dict, str, None
    """
    mySettings = QtCore.QSettings()
    myDefaults = DEFAULTS

    myDefaults['FEM_RATIO'] = float(mySettings.value(
        'inasafe/defaultFemaleRatio',
        DEFAULTS['FEM_RATIO']))

    if theDefault is None:
        return myDefaults
    elif theDefault in myDefaults:
        return myDefaults[theDefault]
    else:
        return None


def create_memory_layer(layer, new_name=''):
    """Return a memory copy of a layer

    :param layer: QgsVectorLayer that shall be copied to memory.
    :type layer: QgsVectorLayer

    :param new_name: The name of the copied layer.
    :type new_name: str

    :returns: An in-memory copy of a layer.
    :rtype: QgsMapLayer
    """

    if new_name is '':
        new_name = layer.name() + ' TMP'

    if layer.type() == QgsMapLayer.VectorLayer:
        vType = layer.geometryType()
        if vType == QGis.Point:
            typeStr = 'Point'
        elif vType == QGis.Line:
            typeStr = 'Line'
        elif vType == QGis.Polygon:
            typeStr = 'Polygon'
        else:
            raise MemoryLayerCreationError('Layer is whether Point nor '
                                           'Line nor Polygon')
    else:
        raise MemoryLayerCreationError('Layer is not a VectorLayer')

    crs = layer.crs().authid().lower()
    myUUID = str(uuid.uuid4())
    uri = '%s?crs=%s&index=yes&uuid=%s' % (typeStr, crs, myUUID)
    memLayer = QgsVectorLayer(uri, new_name, 'memory')
    memProvider = memLayer.dataProvider()

    provider = layer.dataProvider()
    vFields = provider.fields()

    fields = []
    for i in vFields:
        fields.append(i)

    memProvider.addAttributes(fields)

    for ft in provider.getFeatures():
        memProvider.addFeatures([ft])

    return memLayer


def mm_to_points(mm, dpi):
    """Convert measurement in mm to one in points.

    :param mm: A distance in millimeters.
    :type mm: int

    :param dpi: Dots per inch to use for the calculation (based on in the
        print / display medium).
    :type dpi: int

    :returns: mm converted value as points.
    :rtype: int
    """
    myInchAsMM = 25.4
    myPoints = (mm * dpi) / myInchAsMM
    return myPoints


def points_to_mm(points, dpi):
    """Convert measurement in points to one in mm.

    :param points: A distance in points.
    :type points: int

    :param dpi: Dots per inch to use for the calculation (based on in the
        print / display medium).
    :type dpi: int

    :returns: points converted value as mm.
    :rtype: int
    """
    myInchAsMM = 25.4
    myMM = (float(points) / dpi) * myInchAsMM
    return myMM


def dpi_to_meters(dpi):
    """Convert dots per inch (dpi) to dots per meters.

    :param dpi: Dots per inch in the print / display medium.
    :type dpi: int

    :returns: dpi converted value.
    :rtype: int
    """
    myInchAsMM = 25.4
    myInchesPerM = 1000.0 / myInchAsMM
    myDotsPerM = myInchesPerM * dpi
    return myDotsPerM


def setup_printer(filename, resolution=300, page_height=297, page_width=210):
    """Create a QPrinter instance defaulted to print to an A4 portrait pdf.

    :param filename: Filename for the pdf print device.
    :type filename: str

    :param resolution: Resolution (in dpi) for the output.
    :type resolution: int

    :param page_height: Height of the page in mm.
    :type page_height: int

    :param page_width: Width of the page in mm.
    :type page_width: int
    """
    #
    # Create a printer device (we are 'printing' to a pdf
    #
    LOGGER.debug('InaSAFE Map setupPrinter called')
    myPrinter = QtGui.QPrinter()
    myPrinter.setOutputFormat(QtGui.QPrinter.PdfFormat)
    myPrinter.setOutputFileName(filename)
    myPrinter.setPaperSize(
        QtCore.QSizeF(page_width, page_height),
        QtGui.QPrinter.Millimeter)
    myPrinter.setFullPage(True)
    myPrinter.setColorMode(QtGui.QPrinter.Color)
    myPrinter.setResolution(resolution)
    return myPrinter


def humanise_seconds(seconds):
    """Utility function to humanise seconds value into e.g. 10 seconds ago.

    The function will try to make a nice phrase of the seconds count
    provided.

    .. note:: Currently seconds that amount to days are not supported.

    :param seconds: Mandatory seconds value e.g. 1100.
    :type seconds: int

    :returns: A humanised version of the seconds count.
    :rtype: str
    """
    myDays = seconds / (3600 * 24)
    myDayModulus = seconds % (3600 * 24)
    myHours = myDayModulus / 3600
    myHourModulus = myDayModulus % 3600
    myMinutes = myHourModulus / 60

    if seconds < 60:
        return tr('%i seconds' % seconds)
    if seconds < 120:
        return tr('a minute')
    if seconds < 3600:
        return tr('%s minutes' % myMinutes)
    if seconds < 7200:
        return tr('over an hour')
    if seconds < 86400:
        return tr('%i hours and %i minutes' % (myHours, myMinutes))
    else:
        # If all else fails...
        return tr('%i days, %i hours and %i minutes' % (
            myDays, myHours, myMinutes))


def impact_attribution(keywords, inasafe_flag=False):
    """Make a little table for attribution of data sources used in impact.

    :param keywords: A keywords dict for an impact layer.
    :type keywords: dict

    :param inasafe_flag: bool - whether to show a little InaSAFE promotional
        text in the attribution output. Defaults to False.

    :returns: An html snippet containing attribution information for the impact
        layer. If no keywords are present or no appropriate keywords are
        present, None is returned.
    :rtype: safe.messaging.Message
    """
    if keywords is None:
        return None

    myJoinWords = ' - %s ' % tr('sourced from')
    myHazardDetails = tr('Hazard details')
    myHazardTitleKeyword = 'hazard_title'
    myHazardSourceKeyword = 'hazard_source'
    myExposureDetails = tr('Exposure details')
    myExposureTitleKeyword = 'exposure_title'
    myExposureSourceKeyword = 'exposure_source'

    if myHazardTitleKeyword in keywords:
        # We use safe translation infrastructure for this one (rather than Qt)
        myHazardTitle = safeTr(keywords[myHazardTitleKeyword])
    else:
        myHazardTitle = tr('Hazard layer')

    if myHazardSourceKeyword in keywords:
        # We use safe translation infrastructure for this one (rather than Qt)
        myHazardSource = safeTr(keywords[myHazardSourceKeyword])
    else:
        myHazardSource = tr('an unknown source')

    if myExposureTitleKeyword in keywords:
        myExposureTitle = keywords[myExposureTitleKeyword]
    else:
        myExposureTitle = tr('Exposure layer')

    if myExposureSourceKeyword in keywords:
        myExposureSource = keywords[myExposureSourceKeyword]
    else:
        myExposureSource = tr('an unknown source')

    myReport = m.Message()
    myReport.add(m.Heading(myHazardDetails, **INFO_STYLE))
    myReport.add(m.Paragraph(
        myHazardTitle,
        myJoinWords,
        myHazardSource))

    myReport.add(m.Heading(myExposureDetails, **INFO_STYLE))
    myReport.add(m.Paragraph(
        myExposureTitle,
        myJoinWords,
        myExposureSource))

    if inasafe_flag:
        myReport.add(m.Heading(tr('Software notes'), **INFO_STYLE))
        # noinspection PyUnresolvedReferences
        myInaSAFEPhrase = tr(
            'This report was created using InaSAFE version %s. Visit '
            'http://inasafe.org to get your free copy of this software!'
            'InaSAFE has been jointly developed by BNPB, AusAid/AIFDRR & the '
            'World Bank') % (get_version())

        myReport.add(m.Paragraph(m.Text(myInaSAFEPhrase)))
    return myReport


def add_ordered_combo_item(combo, text, data=None):
    """Add a combo item ensuring that all items are listed alphabetically.

    Although QComboBox allows you to set an InsertAlphabetically enum
    this only has effect when a user interactively adds combo items to
    an editable combo. This we have this little function to ensure that
    combos are always sorted alphabetically.

    :param combo: Combo box receiving the new item.
    :type combo: QComboBox

    :param text: Display text for the combo.
    :type text: str

    :param data: Optional UserRole data to be associated with the item.
    :type data: QVariant, str
    """
    mySize = combo.count()
    for myCount in range(0, mySize):
        myItemText = str(combo.itemText(myCount))
        # see if text alphabetically precedes myItemText
        if cmp(str(text).lower(), myItemText.lower()) < 0:
            combo.insertItem(myCount, text, data)
            return
        # otherwise just add it to the end
    combo.insertItem(mySize, text, data)


def is_polygon_layer(layer):
    """Check if a QGIS layer is vector and its geometries are polygons.

    :param layer: A vector layer.
    :type layer: QgsVectorLayer, QgsMapLayer

    :returns: True if the layer contains polygons, otherwise False.
    :rtype: bool

    """
    try:
        return (layer.type() == QgsMapLayer.VectorLayer) and (
            layer.geometryType() == QGis.Polygon)
    except AttributeError:
        return False


def is_point_layer(layer):
    """Check if a QGIS layer is vector and its geometries are points.

    :param layer: A vector layer.
    :type layer: QgsVectorLayer, QgsMapLayer

    :returns: True if the layer contains points, otherwise False.
    :rtype: bool
    """
    try:
        return (layer.type() == QgsMapLayer.VectorLayer) and (
            layer.geometryType() == QGis.Point)
    except AttributeError:
        return False


def is_raster_layer(layer):
    """Check if a QGIS layer is raster.

    :param layer: A layer.
    :type layer: QgsRaster, QgsMapLayer, QgsVectorLayer

    :returns: True if the layer contains polygons, otherwise False.
    :rtype: bool
    """
    try:
        return layer.type() == QgsMapLayer.RasterLayer
    except AttributeError:
        return False


def which(name, flags=os.X_OK):
    """Search PATH for executable files with the given name.

    ..note:: This function was taken verbatim from the twisted framework,
      licence available here:
      http://twistedmatrix.com/trac/browser/tags/releases/twisted-8.2.0/LICENSE

    On newer versions of MS-Windows, the PATHEXT environment variable will be
    set to the list of file extensions for files considered executable. This
    will normally include things like ".EXE". This function will also find
    files
    with the given name ending with any of these extensions.

    On MS-Windows the only flag that has any meaning is os.F_OK. Any other
    flags will be ignored.

    :param name: The name for which to search.
    :type name: C{str}

    :param flags: Arguments to L{os.access}.
    :type flags: C{int}

    :returns: A list of the full paths to files found, in the order in which
        they were found.
    :rtype: C{list}
    """
    result = []
    #pylint: disable=W0141
    exts = filter(None, os.environ.get('PATHEXT', '').split(os.pathsep))
    #pylint: enable=W0141
    path = os.environ.get('PATH', None)
    # In c6c9b26 we removed this hard coding for issue #529 but I am
    # adding it back here in case the user's path does not include the
    # gdal binary dir on OSX but it is actually there. (TS)
    if sys.platform == 'darwin':  # Mac OS X
        myGdalPrefix = ('/Library/Frameworks/GDAL.framework/'
                        'Versions/1.9/Programs/')
        path = '%s:%s' % (path, myGdalPrefix)

    LOGGER.debug('Search path: %s' % path)

    if path is None:
        return []

    for p in path.split(os.pathsep):
        p = os.path.join(p, name)
        if os.access(p, flags):
            result.append(p)
        for e in exts:
            pext = p + e
            if os.access(pext, flags):
                result.append(pext)

    return result


def extent_to_geo_array(extent, source_crs):
    """Convert the supplied extent to geographic and return as an array.

    :param extent: Rectangle defining a spatial extent in any CRS.
    :type extent: QgsRectangle

    :param source_crs: Coordinate system used for extent.
    :type source_crs: QgsCoordinateReferenceSystem

    :returns: a list in the form [xmin, ymin, xmax, ymax] where all
            coordinates provided are in Geographic / EPSG:4326.
    :rtype: list

    """

    myGeoCrs = QgsCoordinateReferenceSystem()
    myGeoCrs.createFromSrid(4326)
    myXForm = QgsCoordinateTransform(source_crs, myGeoCrs)

    # Get the clip area in the layer's crs
    myTransformedExtent = myXForm.transformBoundingBox(extent)

    myGeoExtent = [myTransformedExtent.xMinimum(),
                   myTransformedExtent.yMinimum(),
                   myTransformedExtent.xMaximum(),
                   myTransformedExtent.yMaximum()]
    return myGeoExtent


def safe_to_qgis_layer(layer):
    """Helper function to make a QgsMapLayer from a safe read_layer layer.

    :param layer: Layer object as provided by InaSAFE engine.
    :type layer: read_layer

    :returns: A validated QGIS layer or None.
    :rtype: QgsMapLayer, QgsVectorLayer, QgsRasterLayer, None

    :raises: Exception if layer is not valid.
    """

    # noinspection PyUnresolvedReferences
    myMessage = tr(
        'Input layer must be a InaSAFE spatial object. I got %s'
    ) % (str(type(layer)))
    if not hasattr(layer, 'is_inasafe_spatial_object'):
        raise Exception(myMessage)
    if not layer.is_inasafe_spatial_object:
        raise Exception(myMessage)

    # Get associated filename and symbolic name
    myFilename = layer.get_filename()
    myName = layer.get_name()

    myQGISLayer = None
    # Read layer
    if layer.is_vector:
        myQGISLayer = QgsVectorLayer(myFilename, myName, 'ogr')
    elif layer.is_raster:
        myQGISLayer = QgsRasterLayer(myFilename, myName)

    # Verify that new qgis layer is valid
    if myQGISLayer.isValid():
        return myQGISLayer
    else:
        # noinspection PyUnresolvedReferences
        myMessage = tr('Loaded impact layer "%s" is not valid') % myFilename
        raise Exception(myMessage)


def download_url(manager, url, output_path, progress_dialog=None):
    """Download file from url.

    :param manager: A QNetworkAccessManager instance
    :type manager: QNetworkAccessManager

    :param url: URL of file
    :type url: str

    :param output_path: Output path
    :type output_path: str

    :param progress_dialog: Progress dialog widget

    :returns: True if success, otherwise returns a tuple with format like this
        (QNetworkReply.NetworkError, error_message)
    :raises: IOError - when cannot create output_path
    """

    # prepare output path
    myFile = QFile(output_path)
    if not myFile.open(QFile.WriteOnly):
        raise IOError(myFile.errorString())

    # slot to write data to file
    def write_data():
        """Write data to a file."""
        myFile.write(myReply.readAll())

    myRequest = QNetworkRequest(QUrl(url))
    myReply = manager.get(myRequest)
    myReply.readyRead.connect(write_data)

    if progress_dialog:
        # progress bar
        def progress_event(received, total):
            """Update progress.

            :param received: Data received so far.
            :type received: int
            :param total: Total expected data.
            :type total: int

            """

            # noinspection PyArgumentList
            QCoreApplication.processEvents()

            progress_dialog.setLabelText("%s / %s" % (received, total))
            progress_dialog.setMaximum(total)
            progress_dialog.setValue(received)

        # cancel
        def cancel_action():
            """Cancel download."""
            myReply.abort()

        myReply.downloadProgress.connect(progress_event)
        progress_dialog.canceled.connect(cancel_action)

    # wait until finished
    while not myReply.isFinished():
        # noinspection PyArgumentList
        QCoreApplication.processEvents()

    myFile.close()

    myResult = myReply.error()
    if myResult == QNetworkReply.NoError:
        return True
    else:
        return myResult, str(myReply.errorString())


def viewport_geo_array(map_canvas):
    """Obtain the map canvas current extent in EPSG:4326.

    :param map_canvas: A map canvas instance.
    :type map_canvas: QgsMapCanvas

    :returns: A list in the form [xmin, ymin, xmax, ymax] where all
        coordinates provided are in Geographic / EPSG:4326.
    :rtype: list

    .. note:: Delegates to extent_to_geo_array()
    """

    # get the current viewport extent
    myRect = map_canvas.extent()

    if map_canvas.hasCrsTransformEnabled():
        myCrs = map_canvas.mapRenderer().destinationCrs()
    else:
        # some code duplication from extentToGeoArray here
        # in favour of clarity of logic...
        myCrs = QgsCoordinateReferenceSystem()
        myCrs.createFromSrid(4326)

    return extent_to_geo_array(myRect, myCrs)


def read_impact_layer(impact_layer):
    """Helper function to read and validate a safe native spatial layer.

    :param impact_layer: Layer object as provided by InaSAFE engine.
    :type impact_layer: read_layer

    :returns: Valid QGIS layer or None
    :rtype: None, QgsRasterLayer, QgsVectorLayer
    """

    # noinspection PyUnresolvedReferences
    myMessage = tr('Input layer must be a InaSAFE spatial object. '
                   'I got %s') % (str(type(impact_layer)))
    if not hasattr(impact_layer, 'is_inasafe_spatial_object'):
        raise Exception(myMessage)
    if not impact_layer.is_inasafe_spatial_object:
        raise Exception(myMessage)

    # Get associated filename and symbolic name
    myFilename = impact_layer.get_filename()
    myName = impact_layer.get_name()

    myQGISLayer = None
    # Read layer
    if impact_layer.is_vector:
        myQGISLayer = QgsVectorLayer(myFilename, myName, 'ogr')
    elif impact_layer.is_raster:
        myQGISLayer = QgsRasterLayer(myFilename, myName)

    # Verify that new qgis layer is valid
    if myQGISLayer.isValid():
        return myQGISLayer
    else:
        # noinspection PyUnresolvedReferences
        myMessage = tr(
            'Loaded impact layer "%s" is not valid') % myFilename
        raise Exception(myMessage)
