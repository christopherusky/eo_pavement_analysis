# -*- coding: utf-8 -*-
"""
/***************************************************************************
 EarthObservationPavementAnalysis
                                 A QGIS plugin
 This plugin prepares the data sets to train, validate and assess earth observation imagery for pavement analysis
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-05-01
        git sha              : $Format:%H$
        copyright            : (C) 2024 by TRL Software
        email                : ckettell@trl.co.uk
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os
import math
import logging
from typing import List, Optional

import processing

from . import resources

import subprocess
from qgis.core import (QgsVectorLayer, QgsProject, QgsProcessingFeedback, 
                       QgsApplication, QgsVectorFileWriter, QgsMessageLog,
                       QgsMapLayer, QgsLayerTreeLayer, Qgis)

from PyQt5.QtCore import QVariant, QSettings, QCoreApplication, QTranslator
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QInputDialog, QFileDialog, QDialog
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsField, QgsProcessingFeatureSourceDefinition, QgsFeatureRequest,
    QgsLineString, QgsWkbTypes, QgsLayerTreeLayer, QgsLayerTreeGroup,
    QgsRasterLayer, QgsVectorFileWriter, QgsRectangle, QgsRaster, QgsFields,
    QgsCoordinateReferenceSystem, QgsProcessingFeedback, QgsApplication,
    QgsProcessingException  # Add this import
)

from qgis.core import QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsCoordinateTransformContext

from PyQt5.QtWidgets import QDialog, QProgressBar, QVBoxLayout
from qgis.analysis import QgsNativeAlgorithms

from .resources import *
from .EO_pavement_analysis_dialog import EarthObservationPavementAnalysisDialog


# Constants
PLUGIN_NAME = 'Earth Observation Pavement Analysis'
ICON_PATH = ':/plugins/EO_pavement_analysis/icon.png'
ROAD_CENTRE_LINES_GROUP = "Road Centre Lines"
SAMPLE_GRID_GROUP = "Sample Grid"
SOURCE_RASTERS_GROUP = "Source Rasters"
CLIPPED_RASTERS_GROUP = "Clipped Rasters"
SHAPEFILE_FILTER = "Shapefiles (*.shp);;All Files (*.*)"
RASTER_FILTER = "Raster files (*.TIF *.tif *.tiff *.asc *.img);;All Files (*.*)"

class LayerManager:
    def __init__(self):
        self.project = QgsProject.instance()
        self.logger = logging.getLogger(__name__)

    def find_or_create_group(self, group_name: str) -> QgsLayerTreeGroup:
        root = self.project.layerTreeRoot()
        group = root.findGroup(group_name)
        if not group:
            group = root.addGroup(group_name)
        return group

    def load_vector_layers(self, file_paths: List[str], group_name: str) -> None:
        group = self.find_or_create_group(group_name)
        
        for file_path in file_paths:
            layer_name = os.path.splitext(os.path.basename(file_path))[0]
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
            
            if layer.isValid():
                self.project.addMapLayer(layer, False)
                group.addLayer(layer)
                self.logger.info(f"Loaded layer: {layer_name}")
            else:
                self.logger.error(f"Failed to load layer: {layer_name}")

    def load_source_rasters(self):
        raster_files, _ = QFileDialog.getOpenFileNames(None, "Select Source Raster Files", "", RASTER_FILTER)

        if raster_files:
            virtual_raster = self.create_virtual_raster(raster_files)
            if virtual_raster:
                self.layer_manager.load_raster_layers([virtual_raster], SOURCE_RASTERS_GROUP)
                self.logger.info(f"Loaded virtual raster into {SOURCE_RASTERS_GROUP}.")
            else:
                self.logger.error("Failed to create virtual raster.")

    def load_raster_layers(self, file_paths: List[str], group_name: str) -> List[QgsRasterLayer]:
        group = self.find_or_create_group(group_name)
        raster_layers = []

        for file_path in file_paths:
            layer_name = "Virtual Raster" if file_path.endswith('.vrt') else os.path.splitext(os.path.basename(file_path))[0]
            layer = QgsRasterLayer(file_path, layer_name)
            
            if layer.isValid():
                self.project.addMapLayer(layer, False)
                group.addLayer(layer)
                raster_layers.append(layer)
                self.logger.info(f"Loaded raster: {layer_name}")
            else:
                self.logger.error(f"Failed to load raster: {layer_name}")

        return raster_layers

class EarthObservationPavementAnalysis:
    def __init__(self, iface):
        # Set up logging first, but don't add any handlers yet
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.log_handler = None
        
        self.dlg = EarthObservationPavementAnalysisDialog()

        self.logger.debug("Initializing EarthObservationPavementAnalysis")
        self.logger.debug(f"iface type: {type(iface)}")

        # Save reference to the QGIS interface
        self.iface = iface
        
        self.logger.debug(f"self.iface set to: {self.iface}")

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'EarthObservationPavementAnalysis_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Earth Observation Pavement Analysis')
        self.first_start = None

        self.layer_manager = LayerManager()

        # Initialize processing
        if not QgsApplication.processingRegistry().providers():
            processing.core.Processing.initialize()

        self.setup_logging()

        self.logger.debug("EarthObservationPavementAnalysis initialization complete")

    def setup_logging(self):
        if self.dlg.get_debug_option():
            if not self.log_handler:
                self.log_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), 'plugin_log.txt'))
                self.log_handler.setLevel(logging.DEBUG)
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                self.log_handler.setFormatter(formatter)
                self.logger.addHandler(self.log_handler)
            self.logger.debug("Debug logging enabled")
        else:
            if self.log_handler:
                self.logger.removeHandler(self.log_handler)
                self.log_handler = None
            self.logger.debug("Debug logging disabled")

    def tr(self, message: str) -> str:
        return QCoreApplication.translate('EarthObservationPavementAnalysis', message)

    def add_action(self, icon, text, callback, enabled_flag=True,
                add_to_menu=True, add_to_toolbar=True, status_tip=None,
                whats_this=None, parent=None):
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        self.logger.debug("Entering initGui method")
        icon_path = ':/plugins/EO_pavement_analysis/icon.png'
        self.logger.debug(f"Icon path: {icon_path}")
        self.logger.debug(f"self.iface before add_action: {self.iface}")
        
        icon = QIcon(icon_path)
        self.add_action(
            icon,
            text=self.tr(u'Earth Observation Pavement Analysis'),
            callback=self.run,
            parent=self.iface.mainWindow())
        
        self.first_start = True
        self.logger.debug("Exiting initGui method")
      

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.tr(PLUGIN_NAME), action)
            self.iface.removeToolBarIcon(action)

    def run(self):
        if self.first_start:
            self.first_start = False
            self.dlg = EarthObservationPavementAnalysisDialog()
            self.setup_connections()

        self.populate_layer_list()
        self.setup_logging()  # Call this here to update logging based on current checkbox state
        result = self.dlg.exec_()
        if result:
            self.logger.info("Dialog closed with OK")

    def setup_connections(self):
        self.dlg.pushButton.clicked.connect(self.create_layer_groups)
        self.dlg.loadRoadCentreLinesButton.clicked.connect(self.load_road_centre_lines)
        self.dlg.sectionRoadButton.clicked.connect(self.section_road)
        self.dlg.loadRastersButton.clicked.connect(self.load_source_rasters)
        self.dlg.extractRastersButton.clicked.connect(self.extract_rasters)
        self.dlg.debug_option.stateChanged.connect(self.setup_logging)

    def populate_layer_list(self):
        layers = QgsProject.instance().layerTreeRoot().children()
        layer_names = [layer.name() for layer in layers if isinstance(layer, QgsLayerTreeLayer)]
        self.logger.info("Available layers: " + ", ".join(layer_names))

    def create_layer_groups(self):
        group_names = [ROAD_CENTRE_LINES_GROUP, SAMPLE_GRID_GROUP, SOURCE_RASTERS_GROUP, CLIPPED_RASTERS_GROUP]
        for name in group_names:
            self.layer_manager.find_or_create_group(name)

    def load_road_centre_lines(self):
        layer_files, _ = QFileDialog.getOpenFileNames(None, "Select Road Centre Lines Layers", "", SHAPEFILE_FILTER)
        if layer_files:
            self.layer_manager.load_vector_layers(layer_files, ROAD_CENTRE_LINES_GROUP)

    def create_box_layer(self, road_layer, width, crs_string):
        self.logger.info(f"Starting create_box_layer for {road_layer.name()} with crs_string: {crs_string}")
        sample_grid_group = self.layer_manager.find_or_create_group(SAMPLE_GRID_GROUP)
    
        # Log the CRS information from the road_layer
        self.logger.info(f"Road layer CRS: {road_layer.crs().authid()}")
        self.logger.info(f"Road layer CRS description: {road_layer.crs().description()}")
    
        if not crs_string:
            self.logger.warning("CRS string is empty, attempting to use road layer CRS")
            crs = road_layer.crs()
        else:
            crs = QgsCoordinateReferenceSystem(crs_string)
    
        if not crs.isValid():
            self.logger.error(f"Invalid CRS: {crs_string}")
            self.logger.info("Attempting to create CRS from WKT")
            crs = QgsCoordinateReferenceSystem()
            crs.createFromWkt(road_layer.crs().toWkt())
            if not crs.isValid():
                self.logger.error("Failed to create valid CRS. Aborting box layer creation.")
                return

        self.logger.info(f"CRS created successfully: {crs.authid()}")

        box_layer_name = f"{road_layer.name()}_bounding_boxes"
        box_file_path = os.path.join(self.output_folder, f"{box_layer_name}.shp")

        uri = f"Polygon?crs={crs.authid()}&field=id:integer&field=road_id:integer"
        mem_layer = QgsVectorLayer(uri, box_layer_name, "memory")

        if not mem_layer.isValid():
            self.logger.error("Failed to create memory layer")
            return

        mem_layer.startEditing()

        box_count = 0
        for feature in road_layer.getFeatures():
            road_id = feature.id()
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            if geom.isMultipart():
                lines = geom.asMultiPolyline()
            else:
                lines = [geom.asPolyline()]

            for line in lines:
                for i in range(0, len(line) - 1):
                    start_point = line[i]
                    end_point = line[i + 1]
                    segment_length = math.sqrt(
                        (end_point.x() - start_point.x()) ** 2 + (end_point.y() - start_point.y()) ** 2)

                    num_boxes = int(segment_length / (width / 2))
                    segment_angle = math.atan2(end_point.y() - start_point.y(), end_point.x() - start_point.x())

                    for n in range(num_boxes):
                        box_count += 1
                        offset = (n + 0.5) * (width / 2)
                        mid_x = start_point.x() + math.cos(segment_angle) * offset
                        mid_y = start_point.y() + math.sin(segment_angle) * offset
                        mid_point = QgsPointXY(mid_x, mid_y)

                        points = []
                        for j in [math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4]:
                            dx = math.cos(segment_angle + j) * (width / (2 * math.sqrt(2)))
                            dy = math.sin(segment_angle + j) * (width / (2 * math.sqrt(2)))
                            points.append(QgsPointXY(mid_point.x() + dx, mid_point.y() + dy))

                        box_feature = QgsFeature()
                        box_feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
                        box_feature.setAttributes([box_count, road_id])

                        mem_layer.addFeature(box_feature)

        mem_layer.commitChanges()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"
        options.fileEncoding = "UTF-8"

        error = QgsVectorFileWriter.writeAsVectorFormat(mem_layer, box_file_path, options)

        if error[0] != QgsVectorFileWriter.NoError:
            self.logger.error(f"Error saving vector layer: {error}")
            return

        box_layer = QgsVectorLayer(box_file_path, box_layer_name, "ogr")
        if not box_layer.isValid():
            self.logger.error(f"Layer failed to load: {box_file_path}")
        else:
            QgsProject.instance().addMapLayer(box_layer, False)
            sample_grid_group.addLayer(box_layer)
            self.logger.info(f"Added bounding box layer: {box_layer_name}")

        self.logger.info(f"Created {box_count} bounding boxes for {road_layer.name()}.")

    def section_road(self):
            root = QgsProject.instance().layerTreeRoot()
            road_group = root.findGroup(ROAD_CENTRE_LINES_GROUP)
            if not road_group:
                self.logger.info(f"{ROAD_CENTRE_LINES_GROUP} group not found.")
                return

            road_width, ok = QInputDialog.getInt(None, "Road Width", "Enter road width (3-15 in meters):", min=3, max=15, step=1)
            if not ok:
                self.logger.info("Road width selection cancelled.")
                return

            self.output_folder = QFileDialog.getExistingDirectory(None, "Select Output Folder for Bounding Box Shapefiles")
            if not self.output_folder:
                self.logger.info("No output folder selected. Operation cancelled.")
                return

            for child in road_group.children():
                if isinstance(child, QgsLayerTreeLayer):
                    layer = child.layer()
                    if layer.geometryType() == QgsWkbTypes.LineGeometry:
                        self.logger.info(f"Processing layer: {layer.name()}")
                        self.logger.info(f"Layer CRS: {layer.crs().authid()}")
                        self.create_box_layer(layer, road_width, layer.crs().authid())
                    else:
                        self.logger.info(f"{layer.name()} is not a valid line layer.")

            self.logger.info("Road sectioning completed.")

    def load_source_rasters(self):
        raster_files, _ = QFileDialog.getOpenFileNames(None, "Select Source Raster Files", "", RASTER_FILTER)
        
        if raster_files:
            virtual_raster = self.create_virtual_raster(raster_files)
            if virtual_raster:
                raster_layers = self.layer_manager.load_raster_layers([virtual_raster], SOURCE_RASTERS_GROUP)
                if not raster_layers:
                    self.logger.error("Failed to load virtual raster layer.")
                    return
                self.logger.info(f"Loaded virtual raster layer into {SOURCE_RASTERS_GROUP}.")
            else:
                self.logger.error("Failed to create virtual raster.")
        else:
            self.logger.info("No raster files selected.")

    def create_virtual_raster(self, raster_files):
        self.logger.info("Creating virtual raster")
        
        output_folder = QFileDialog.getExistingDirectory(None, "Select Output Folder for Virtual Raster")
        if not output_folder:
            self.logger.info("No output folder selected. Operation cancelled.")
            return None

        output_vrt = os.path.join(output_folder, "virtual_raster.vrt")

        params = {
            'INPUT': raster_files,
            'RESOLUTION': 0,  # 0 = average
            'SEPARATE': False,
            'PROJ_DIFFERENCE': False,
            'ADD_ALPHA': False,
            'ASSIGN_CRS': None,
            'RESAMPLING': 0,  # 0 = nearest neighbor
            'SRC_NODATA': '',
            'OUTPUT': output_vrt
        }

        try:
            result = processing.run("gdal:buildvirtualraster", params)
            self.logger.info(f"Virtual raster created: {result['OUTPUT']}")
            return result['OUTPUT']
        except QgsProcessingException as e:
            self.logger.error(f"Error creating virtual raster: {str(e)}")
            return None

    def extract_rasters(self):
        self.logger.info("Starting raster extraction process")

        root = QgsProject.instance().layerTreeRoot()
        sample_grid_group = root.findGroup(SAMPLE_GRID_GROUP)
        raster_group = root.findGroup(SOURCE_RASTERS_GROUP)

        if not sample_grid_group or not raster_group:
            self.logger.error("Required groups not found.")
            return

        virtual_raster_layer = self.find_virtual_raster(raster_group)
        if not virtual_raster_layer:
            self.logger.error("Virtual raster layer not found.")
            return

        output_folder = QFileDialog.getExistingDirectory(None, "Select Output Folder for Raster Extracts")
        if not output_folder:
            self.logger.info("No output folder selected. Operation cancelled.")
            return

        for box_child in sample_grid_group.children():
            if isinstance(box_child, QgsLayerTreeLayer):
                box_layer = box_child.layer()
                if isinstance(box_layer, QgsVectorLayer) and box_layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    self.logger.info(f"Processing bounding boxes from: {box_layer.name()}")
                    self.extract_raster_areas_gdalwarp(virtual_raster_layer, box_layer, output_folder)

        self.logger.info("Raster extraction process completed")

    def find_virtual_raster(self, raster_group):
        for child in raster_group.children():
            if isinstance(child, QgsLayerTreeLayer):
                layer = child.layer()
                if isinstance(layer, QgsRasterLayer):
                    return layer
        return None

    def extract_raster_areas_gdalwarp(self, raster_layer, box_layer, output_folder):
        self.logger.info(f"Extracting areas from {raster_layer.name()} using {box_layer.name()}")

        raster_output_folder = os.path.join(output_folder, f"{raster_layer.name()}_extracts")
        os.makedirs(raster_output_folder, exist_ok=True)

        if box_layer.crs() != raster_layer.crs():
            self.logger.info(f"Reprojecting box layer to match raster CRS: {raster_layer.crs().authid()}")
            reprojected_layer = processing.run("native:reprojectlayer", {
                'INPUT': box_layer,
                'TARGET_CRS': raster_layer.crs(),
                'OUTPUT': 'memory:'
            })['OUTPUT']
            box_layer = reprojected_layer

        total_features = box_layer.featureCount()
        for index, box_feature in enumerate(box_layer.getFeatures(), 1):
            box_id = box_feature.id()
            output_file = os.path.join(raster_output_folder, f"rasters_{box_id}.tif")

            temp_layer_path = os.path.join(raster_output_folder, f"temp_shapefile_{box_id}.shp")
            temp_layer = QgsVectorLayer("Polygon?crs=" + box_layer.crs().authid(), "temp", "memory")
            dp = temp_layer.dataProvider()
            dp.addFeature(box_feature)
            _ = QgsVectorFileWriter.writeAsVectorFormat(temp_layer, temp_layer_path, "UTF-8", temp_layer.crs(), "ESRI Shapefile")

            gdal_options = [
                '-of', 'GTiff',
                '-cutline', temp_layer_path,
                '-crop_to_cutline',
                '-tr', str(raster_layer.rasterUnitsPerPixelX()), str(raster_layer.rasterUnitsPerPixelY()),
                '-tap'
            ]

            try:
                command = ['gdalwarp'] + gdal_options + [raster_layer.source(), output_file]
                result = subprocess.run(command, check=True, capture_output=True, text=True)
                if os.path.exists(output_file):
                    file_size = os.path.getsize(output_file)
                    self.logger.info(f"Extracted raster for box {box_id} saved to {output_file} (Size: {file_size} bytes)")
                else:
                    self.logger.warning(f"Output file for box {box_id} was not created: {output_file}")
                self.logger.info(f"GDAL command: {' '.join(command)}")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Error extracting raster for box {box_id}: {e.stderr}")
            except Exception as e:
                self.logger.error(f"Unexpected error extracting raster for box {box_id}: {str(e)}")
            finally:
                if os.path.exists(temp_layer_path):
                    os.remove(temp_layer_path)

            # Update progress
            progress = int((index / total_features) * 100)
            self.set_progress(progress)

            # Give QGIS a chance to process events and remain responsive
            QgsApplication.processEvents()

        self.set_progress(100)  # Ensure the progress bar reaches 100% at the end
        
        # Final check of created files
        created_files = os.listdir(raster_output_folder)
        self.logger.info(f"Total files created in {raster_output_folder}: {len(created_files)}")
        
        self.logger.info(f"Completed raster extraction for {raster_layer.name()}")

    def get_constant_width(self) -> bool:
        return self.dlg.get_constant_width()

    def get_box_width(self) -> float:
        return self.dlg.get_box_width()

    def set_progress(self, value: int) -> None:
        self.dlg.set_progress(value)

    def show_message(self, message: str) -> None:
        self.dlg.show_message(message)

    def clear_messages(self) -> None:
        self.dlg.clear_messages()

    def enable_buttons(self, enable: bool) -> None:
        self.dlg.enable_buttons(enable)

# Add this line at the end of the file, outside of the class
if __name__ == "__main__":
    pass