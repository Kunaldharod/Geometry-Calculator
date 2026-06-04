import os
import math
import csv
import traceback
from qgis.PyQt.QtWidgets import (
    QAction, QFileDialog, QDialog, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QLineEdit, QProgressBar, QMessageBox, QHBoxLayout,
    QSpinBox, QGroupBox, QFormLayout, QTextEdit, QFrame, QSplitter,
    QComboBox, QWidget, QScrollArea
)
from qgis.PyQt.QtGui import QFont, QIcon, QPalette, QColor, QPixmap, QPainter
from qgis.PyQt.QtCore import QVariant, QThread, pyqtSignal, Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsCoordinateTransform,
    QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
    QgsField, QgsVectorDataProvider, QgsWkbTypes, QgsMessageLog,
    Qgis, QgsTask, QgsApplication, QgsVectorFileWriter, QgsFields
)


class GeometryCalculationTask(QgsTask):
    """Background task for geometry calculations to prevent UI freezing"""
    
    # Define custom signals
    taskCompleted = pyqtSignal()
    taskTerminated = pyqtSignal()
    statusUpdate = pyqtSignal(str)
    
    def __init__(self, layers_data, buffer_enabled, buffer_distance, output_dir, export_formats):
        super().__init__('Geometry Calculation', QgsTask.CanCancel)
        self.layers_data = layers_data
        self.buffer_enabled = buffer_enabled
        self.buffer_distance = buffer_distance
        self.output_dir = output_dir
        self.export_formats = export_formats  # ['shp', 'kml']
        self.results = []
        self.error_message = None
        
    def run(self):
        """Execute the geometry calculations"""
        try:
            total_layers = len(self.layers_data)
            self.statusUpdate.emit(f"Processing {total_layers} layer(s)...")
            
            for i, (layer, layer_name) in enumerate(self.layers_data):
                if self.isCanceled():
                    return False
                    
                # Update progress for layers
                layer_progress = int((i / total_layers) * 100)
                self.setProgress(layer_progress)
                self.statusUpdate.emit(f"Processing layer: {layer_name}")
                
                result = self.process_layer(layer, layer_name)
                if result:
                    self.results.append(result)
                    
            self.statusUpdate.emit("Processing completed successfully!")
            return True
            
        except Exception as e:
            self.error_message = str(e)
            QgsMessageLog.logMessage(f"Geometry Calc Error: {traceback.format_exc()}", 
                                   "GeometryCalc", Qgis.Critical)
            self.statusUpdate.emit(f"Error: {str(e)}")
            return False
    
    def finished(self, result):
        """Called when task finishes"""
        if result:
            self.taskCompleted.emit()
        else:
            self.taskTerminated.emit()
    
    def process_layer(self, layer, layer_name):
        """Process a single layer"""
        try:
            output_layer_name = f"{layer_name}_geometry_calc"
            
            # Create memory layers for original and buffer geometries
            original_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", f"{output_layer_name}_original", "memory")
            buffer_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", f"{output_layer_name}_buffer", "memory") if self.buffer_enabled else None
            
            # Setup providers
            original_provider = original_layer.dataProvider()
            self.add_output_fields(original_provider)
            original_layer.updateFields()
            
            if buffer_layer:
                buffer_provider = buffer_layer.dataProvider()
                self.add_output_fields(buffer_provider)
                buffer_layer.updateFields()
            
            # Prepare CSV output
            csv_path = os.path.join(self.output_dir, f"{layer_name}_geometry_calc_output.csv")
            csv_rows = [["Name", "Zone", "Value", "Buffer_Area_km2", "Buffer_Dist_M", "Value_Type", "Original_Geometry_Type", "Geometry_Category"]]
            
            # Process features
            features = list(layer.getFeatures())
            total_features = len(features)
            
            if total_features == 0:
                self.statusUpdate.emit(f"Warning: Layer {layer_name} has no features")
                return None
            
            # Get layer CRS once
            source_crs = layer.crs()
            
            original_features = []
            buffer_features = []
            
            for idx, feature in enumerate(features):
                if self.isCanceled():
                    return None
                    
                # Update progress within layer
                if total_features > 0:
                    feature_progress = ((idx + 1) / total_features)
                    try:
                        layer_idx = next(i for i, (l, n) in enumerate(self.layers_data) if l == layer and n == layer_name)
                        overall_progress = int((layer_idx / len(self.layers_data)) * 100 + (feature_progress * 100 / len(self.layers_data)))
                        overall_progress = max(0, min(100, overall_progress))
                        self.setProgress(overall_progress)
                    except (StopIteration, ZeroDivisionError):
                        pass
                
                geom = feature.geometry()
                if geom.isEmpty() or not geom.isGeosValid():
                    continue
                
                # Calculate geometry properties
                geom_data = self.calculate_geometry_properties(
                    geom, source_crs, feature, self.buffer_enabled, self.buffer_distance
                )
                
                if geom_data:
                    # Separate original and buffer features
                    for data in geom_data:
                        feat = QgsFeature()
                        feat.setGeometry(data['geometry'])
                        feat.setAttributes([
                            data['name'], data['zone'], data['value'], 
                            data['buffer_area'], data['buffer_distance'], 
                            data['value_type'], data['original_geom_type'], data['geometry_category']
                        ])
                        
                        if data['geometry_category'] == 'buffer':
                            buffer_features.append(feat)
                        else:
                            original_features.append(feat)
                        
                        # Add to CSV
                        csv_rows.append([
                            data['name'], data['zone'], data['value'], 
                            data['buffer_area'], data['buffer_distance'], 
                            data['value_type'], data['original_geom_type'], data['geometry_category']
                        ])
            
            # Add features to layers
            if original_features:
                original_provider.addFeatures(original_features)
            
            if buffer_features and buffer_layer:
                buffer_provider.addFeatures(buffer_features)
            
            # Save CSV
            self.save_csv(csv_path, csv_rows)
            
            # Export to additional formats
            exported_files = []
            
            # Export original geometries
            if original_features and self.export_formats:
                for fmt in self.export_formats:
                    if fmt == 'shp':
                        shp_path = os.path.join(self.output_dir, f"{layer_name}_original.shp")
                        if self.export_to_shapefile(original_layer, shp_path):
                            exported_files.append(shp_path)
                    elif fmt == 'kml':
                        kml_path = os.path.join(self.output_dir, f"{layer_name}_original.kml")
                        if self.export_to_kml(original_layer, kml_path):
                            exported_files.append(kml_path)
            
            # Export buffer geometries (if they exist)
            if buffer_features and buffer_layer and self.export_formats:
                for fmt in self.export_formats:
                    if fmt == 'shp':
                        shp_path = os.path.join(self.output_dir, f"{layer_name}_buffer.shp")
                        if self.export_to_shapefile(buffer_layer, shp_path):
                            exported_files.append(shp_path)
                    elif fmt == 'kml':
                        kml_path = os.path.join(self.output_dir, f"{layer_name}_buffer.kml")
                        if self.export_to_kml(buffer_layer, kml_path):
                            exported_files.append(kml_path)
            
            result = {
                'original_layer': original_layer if original_features else None,
                'buffer_layer': buffer_layer if buffer_features else None,
                'csv_path': csv_path,
                'exported_files': exported_files,
                'layer_name': output_layer_name
            }
            
            self.statusUpdate.emit(f"Completed: {layer_name} ({len(original_features)} original, {len(buffer_features)} buffer features)")
            
            return result
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error processing layer {layer_name}: {str(e)}", 
                                   "GeometryCalc", Qgis.Critical)
            self.statusUpdate.emit(f"Error processing {layer_name}: {str(e)}")
            return None
    
    def add_output_fields(self, provider):
        """Add fields to output layer"""
        fields = [
            QgsField("Name", QVariant.String),
            QgsField("Zone", QVariant.Int),
            QgsField("Value", QVariant.Double),
            QgsField("Buffer_Area_km2", QVariant.Double),
            QgsField("Buffer_Dist_M", QVariant.Double),
            QgsField("Value_Type", QVariant.String),
            QgsField("Original_Geometry_Type", QVariant.String),
            QgsField("Geometry_Category", QVariant.String)
        ]
        provider.addAttributes(fields)
    
    def calculate_geometry_properties(self, geom, source_crs, feature, buffer_enabled, buffer_distance):
        """Calculate geometry properties with proper CRS handling"""
        results = []
        
        try:
            # Get feature name
            feature_name = self.get_feature_name(feature)
            
            # Calculate UTM zone more robustly
            centroid = geom.centroid().asPoint()
            zone_number = self.calculate_utm_zone(centroid.x(), centroid.y())
            
            # Handle southern hemisphere
            hemisphere = 'N' if centroid.y() >= 0 else 'S'
            epsg_code = f"326{zone_number:02d}" if hemisphere == 'N' else f"327{zone_number:02d}"
            
            utm_crs = QgsCoordinateReferenceSystem(f'EPSG:{epsg_code}')
            
            if not utm_crs.isValid():
                QgsMessageLog.logMessage(f"Invalid UTM CRS: EPSG:{epsg_code}", "GeometryCalc", Qgis.Warning)
                return None
            
            # Transform to UTM
            transform_to_utm = QgsCoordinateTransform(source_crs, utm_crs, QgsProject.instance())
            transform_from_utm = QgsCoordinateTransform(utm_crs, source_crs, QgsProject.instance())
            
            geom_utm = QgsGeometry(geom)
            if geom_utm.transform(transform_to_utm) != 0:
                QgsMessageLog.logMessage("Failed to transform geometry to UTM", "GeometryCalc", Qgis.Warning)
                return None
            
            # Calculate value based on geometry type
            geom_type = QgsWkbTypes.geometryType(geom.wkbType())
            value, value_type, original_geom_type = self.get_geometry_value(geom_utm, geom_type)
            
            if value is None:
                return None
            
            # For lines and points, convert to polygon for consistent processing
            display_geom = geom
            if geom_type in [QgsWkbTypes.LineGeometry, QgsWkbTypes.PointGeometry]:
                # Create a small buffer for visualization (1 meter in UTM)
                small_buffer = geom_utm.buffer(1, 8)
                if not small_buffer.isEmpty():
                    small_buffer.transform(transform_from_utm)
                    display_geom = small_buffer
            
            # Original geometry data
            geom_data = {
                'geometry': display_geom,
                'name': feature_name,
                'zone': zone_number,
                'value': value,
                'buffer_area': None,
                'buffer_distance': 0,
                'value_type': value_type,
                'original_geom_type': original_geom_type,
                'geometry_category': 'original'
            }
            results.append(geom_data)
            
            # Buffer calculation if enabled - FIXED: Ensure buffer is always created for all geometry types
            if buffer_enabled and buffer_distance > 0:
                buffer_geom = geom_utm.buffer(buffer_distance, 8)
                if not buffer_geom.isEmpty():
                    buffer_area = buffer_geom.area() / 1e6  # Convert to km²
                    
                    # Transform buffer back to original CRS
                    if buffer_geom.transform(transform_from_utm) == 0:
                        buffer_data = {
                            'geometry': buffer_geom,
                            'name': f"{feature_name}_buffer",
                            'zone': zone_number,
                            'value': buffer_area,  # Buffer area as value
                            'buffer_area': buffer_area,
                            'buffer_distance': buffer_distance,
                            'value_type': f"Buffer_Area_km2",
                            'original_geom_type': original_geom_type,
                            'geometry_category': 'buffer'
                        }
                        results.append(buffer_data)
                        
                        # Update original geometry data with buffer info
                        geom_data['buffer_area'] = buffer_area
                        geom_data['buffer_distance'] = buffer_distance
                    else:
                        QgsMessageLog.logMessage("Failed to transform buffer back to original CRS", "GeometryCalc", Qgis.Warning)
                else:
                    QgsMessageLog.logMessage("Buffer geometry is empty", "GeometryCalc", Qgis.Warning)
            
            return results
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error calculating geometry properties: {str(e)}", "GeometryCalc", Qgis.Critical)
            return None
    
    def get_feature_name(self, feature):
        """Extract feature name from various possible field names"""
        name_fields = ['Name', 'NAME', 'name', 'id', 'ID', 'Id', 'fid', 'FID']
        
        for field_name in name_fields:
            if field_name in feature.fields().names():
                name = feature[field_name]
                if name is not None and str(name).strip():
                    return str(name).strip()
        
        return f"Feature_{feature.id()}"
    
    def calculate_utm_zone(self, lon, lat):
        """Calculate UTM zone number with special case handling"""
        # Special cases for Norway and Svalbard
        if 56 <= lat < 64 and 3 <= lon < 12:
            return 32
        if 72 <= lat < 84:
            if 0 <= lon < 9:
                return 31
            elif 9 <= lon < 21:
                return 33
            elif 21 <= lon < 33:
                return 35
            elif 33 <= lon < 42:
                return 37
        
        # Standard UTM zone calculation
        zone = int((lon + 180) / 6) + 1
        return max(1, min(60, zone))  # Ensure zone is between 1-60
    
    def get_geometry_value(self, geom_utm, geom_type):
        """Calculate geometry value based on type"""
        if geom_type == QgsWkbTypes.PolygonGeometry:
            return geom_utm.area() / 1e6, "Area_km2", "Polygon"  # km²
        elif geom_type == QgsWkbTypes.LineGeometry:
            return geom_utm.length() / 1e3, "Length_km", "LineString"  # km
        elif geom_type == QgsWkbTypes.PointGeometry:
            return 1.0, "Point_Count", "Point"  # Point count
        else:
            return None, None, "Unknown"
    
    def export_to_shapefile(self, layer, output_path):
        """Export layer to shapefile"""
        try:
            error = QgsVectorFileWriter.writeAsVectorFormat(
                layer,
                output_path,
                "utf-8",
                layer.crs(),
                "ESRI Shapefile"
            )
            if error[0] == QgsVectorFileWriter.NoError:
                self.statusUpdate.emit(f"Exported: {os.path.basename(output_path)}")
                return True
            else:
                QgsMessageLog.logMessage(f"Export error: {error[1]}", "GeometryCalc", Qgis.Warning)
                return False
        except Exception as e:
            QgsMessageLog.logMessage(f"Shapefile export error: {str(e)}", "GeometryCalc", Qgis.Critical)
            return False
    
    def export_to_kml(self, layer, output_path):
        """Export layer to KML"""
        try:
            # Transform to WGS84 for KML
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            error = QgsVectorFileWriter.writeAsVectorFormat(
                layer,
                output_path,
                "utf-8",
                wgs84_crs,
                "KML"
            )
            if error[0] == QgsVectorFileWriter.NoError:
                self.statusUpdate.emit(f"Exported: {os.path.basename(output_path)}")
                return True
            else:
                QgsMessageLog.logMessage(f"KML export error: {error[1]}", "GeometryCalc", Qgis.Warning)
                return False
        except Exception as e:
            QgsMessageLog.logMessage(f"KML export error: {str(e)}", "GeometryCalc", Qgis.Critical)
            return False
    
    def save_csv(self, csv_path, csv_rows):
        """Save CSV file with error handling"""
        try:
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(csv_rows)
            self.statusUpdate.emit(f"Saved CSV: {os.path.basename(csv_path)}")
        except Exception as e:
            QgsMessageLog.logMessage(f"Error saving CSV: {str(e)}", "GeometryCalc", Qgis.Critical)


class StyledWidget(QWidget):
    """Custom styled widget with gradient background"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)


class GeometryCalc:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon.png")), 
            "Geometry Calc", 
            iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.file_paths = []
        self.dialog = None
        self.current_task = None

    def initGui(self):
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Geometry Calc", self.action)

    def unload(self):
        if self.current_task:
            self.current_task.cancel()
        self.iface.removePluginMenu("&Geometry Calc", self.action)
        self.iface.removeToolBarIcon(self.action)

    def create_styled_button(self, text, color="#3498db", hover_color="#2980b9", text_color="white"):
        """Create a styled button with professional colors"""
        button = QPushButton(text)
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                border: none;
                color: {text_color};
                padding: 12px 24px;
                text-align: center;
                font-size: 13px;
                font-weight: 600;
                border-radius: 6px;
                margin: 4px 2px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            }}
            QPushButton:pressed {{
                background-color: {hover_color};
                transform: translateY(0px);
            }}
            QPushButton:disabled {{
                background-color: #95a5a6;
                color: #7f8c8d;
            }}
        """)
        return button

    def create_styled_groupbox(self, title, color="#3498db"):
        """Create a styled group box with professional theme"""
        group = QGroupBox(title)
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 13px;
                font-weight: 600;
                border: 2px solid {color};
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 12px;
                background-color: rgba(255, 255, 255, 0.98);
                color: #2c3e50;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
                background-color: {color};
                color: white;
                border-radius: 4px;
                font-weight: 600;
            }}
        """)
        return group

    def run(self):
        """Show the plugin dialog with enhanced UI"""
        self.dialog = QDialog()
        self.dialog.setWindowTitle("🌍 Geometry Calculator Pro")
        self.dialog.setMinimumSize(700, 600)
        self.dialog.resize(800, 700)
        
        # Set main dialog style with professional color scheme
        self.dialog.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2c3e50, stop:0.5 #34495e, stop:1 #2c3e50);
            }
            QLabel {
                color: #333333;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLineEdit, QSpinBox, QComboBox {
                padding: 8px;
                border: 2px solid #ddd;
                border-radius: 6px;
                font-size: 12px;
                background-color: white;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #4CAF50;
            }
            QCheckBox {
                font-size: 12px;
                color: #333333;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #ccc;
                border-radius: 3px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #4CAF50;
                border-radius: 3px;
                background-color: #4CAF50;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 8px;
                text-align: center;
                font-weight: bold;
                background-color: white;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:1 #8BC34A);
                border-radius: 6px;
            }
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 8px;
                padding: 8px;
                background-color: rgba(255, 255, 255, 0.95);
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)

        main_layout = QVBoxLayout()

        # Title with professional styling
        title_label = QLabel("⚡ Geometry Calculator Pro")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 22px;
                font-weight: 700;
                color: white;
                background-color: rgba(52, 73, 94, 0.9);
                padding: 16px;
                border-radius: 8px;
                text-align: center;
                border: 2px solid #3498db;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Create scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        # File selection group
        file_group = self.create_styled_groupbox("📁 File Selection", "#2c3e50")
        file_layout = QVBoxLayout()
        
        self.file_button = self.create_styled_button("📂 Select Spatial Files", "#2c3e50", "#34495e")
        self.file_button.clicked.connect(self.select_files)
        file_layout.addWidget(self.file_button)

        self.selected_file_label = QLabel("No files selected")
        self.selected_file_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                padding: 10px;
                background-color: rgba(236, 240, 241, 0.9);
                border-radius: 4px;
                color: #2c3e50;
                border: 1px solid #bdc3c7;
            }
        """)
        self.selected_file_label.setWordWrap(True)
        file_layout.addWidget(self.selected_file_label)

        self.use_active_layer_checkbox = QCheckBox("✅ Include active layer from QGIS")
        file_layout.addWidget(self.use_active_layer_checkbox)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Buffer settings group
        buffer_group = self.create_styled_groupbox("🔍 Buffer Analysis", "#27ae60")
        buffer_layout = QFormLayout()
        
        self.apply_buffer_checkbox = QCheckBox("Enable Buffer Analysis")
        
        buffer_input_layout = QHBoxLayout()
        self.buffer_distance_input = QSpinBox()
        self.buffer_distance_input.setRange(1, 100000)
        self.buffer_distance_input.setValue(100)
        self.buffer_distance_input.setSuffix(" meters")
        buffer_input_layout.addWidget(self.buffer_distance_input)
        
        buffer_layout.addRow(self.apply_buffer_checkbox)
        buffer_layout.addRow("Buffer Distance:", self.buffer_distance_input)
        
        buffer_group.setLayout(buffer_layout)
        layout.addWidget(buffer_group)

        # Export format group
        export_group = self.create_styled_groupbox("💾 Export Options", "#8e44ad")
        export_layout = QVBoxLayout()
        
        self.export_shp_checkbox = QCheckBox("Export as Shapefile (.shp)")
        self.export_shp_checkbox.setChecked(True)
        
        self.export_kml_checkbox = QCheckBox("Export as KML (.kml)")
        self.export_kml_checkbox.setChecked(True)
        
        export_layout.addWidget(self.export_shp_checkbox)
        export_layout.addWidget(self.export_kml_checkbox)
        
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        # Output settings group
        output_group = self.create_styled_groupbox("📂 Output Configuration", "#e67e22")
        output_layout = QFormLayout()
        
        output_dir_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit()
        
        # Set default output directory to the first selected file's directory or Desktop
        self.output_dir_input.setText(os.path.expanduser("~/Desktop"))
        
        self.output_dir_button = self.create_styled_button("Browse", "#e67e22", "#d35400", "white")
        self.output_dir_button.clicked.connect(self.select_output_directory)
        
        output_dir_layout.addWidget(self.output_dir_input)
        output_dir_layout.addWidget(self.output_dir_button)
        
        output_layout.addRow("Output Directory:", output_dir_layout)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                height: 25px;
                font-size: 12px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.progress)

        # Status text
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(120)
        self.status_text.setVisible(False)
        self.status_text.setPlaceholderText("📊 Processing status will appear here...")
        layout.addWidget(self.status_text)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        # Buttons
        button_layout = QHBoxLayout()
        
        self.run_button = self.create_styled_button("▶ Run Analysis", "#27ae60", "#229954")
        self.run_button.clicked.connect(self.process_data)
        
        self.cancel_button = self.create_styled_button("⏹ Cancel", "#e74c3c", "#c0392b")
        self.cancel_button.clicked.connect(self.cancel_processing)
        self.cancel_button.setVisible(False)
        
        close_button = self.create_styled_button("✖ Close", "#95a5a6", "#7f8c8d")
        close_button.clicked.connect(self.dialog.close)
        
        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        
        main_layout.addLayout(button_layout)

        self.dialog.setLayout(main_layout)
        self.dialog.exec_()

    def select_files(self):
        """Select input files and auto-set output directory"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            None, 
            "Select Spatial Files", 
            "", 
            "Vector Files (*.shp *.kml *.kmz *.gpkg *.geojson *.gml);;Shapefiles (*.shp);;KML Files (*.kml *.kmz);;GeoPackage (*.gpkg);;GeoJSON (*.geojson)"
        )
        if file_paths:
            self.file_paths = file_paths
            filenames = [os.path.basename(p) for p in file_paths]
            
            # Auto-set output directory to the first file's directory
            first_file_dir = os.path.dirname(file_paths[0])
            self.output_dir_input.setText(first_file_dir)
            
            if len(filenames) <= 3:
                file_list = ', '.join(filenames)
            else:
                file_list = ', '.join(filenames[:3]) + f' + {len(filenames)-3} more files'
            
            self.selected_file_label.setText(f"Selected {len(filenames)} file(s):\n{file_list}")

    def select_output_directory(self):
        """Select output directory"""
        directory = QFileDialog.getExistingDirectory(None, "📁 Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)

    def process_data(self):
        """Process the selected data"""
        # Validate inputs
        buffer_enabled = self.apply_buffer_checkbox.isChecked()
        buffer_distance = self.buffer_distance_input.value() if buffer_enabled else 0
        output_dir = self.output_dir_input.text()

        # Get export formats
        export_formats = []
        if self.export_shp_checkbox.isChecked():
            export_formats.append('shp')
        if self.export_kml_checkbox.isChecked():
            export_formats.append('kml')

        if not export_formats:
            QMessageBox.warning(None, "Warning", "Please select at least one export format (SHP or KML).")
            return

        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(None, "❌ Error", f"Cannot create output directory:\n{str(e)}")
                return

        # Collect layers to process
        layers_to_process = []

        # Add selected files
        for file_path in self.file_paths:
            layer_name = os.path.splitext(os.path.basename(file_path))[0]
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
            if layer.isValid():
                layers_to_process.append((layer, layer_name))
            else:
                QgsMessageLog.logMessage(f"Invalid layer: {file_path}", "GeometryCalc", Qgis.Warning)

        # Add active layer if requested
        if self.use_active_layer_checkbox.isChecked():
            active_layer = self.iface.activeLayer()
            if active_layer and isinstance(active_layer, QgsVectorLayer):
                layer_name = active_layer.name().replace(' ', '_')
                layers_to_process.append((active_layer, layer_name))

        if not layers_to_process:
            QMessageBox.warning(None, "Warning", "No valid layers to process.\nPlease select files or check active layer.")
            return

        # Setup UI for processing
        self.run_button.setVisible(False)
        self.cancel_button.setVisible(True)
        self.progress.setVisible(True)
        self.status_text.setVisible(True)
        self.status_text.clear()
        self.status_text.append(f"Starting processing of {len(layers_to_process)} layer(s)...")
        self.status_text.append(f"Buffer: {'Enabled' if buffer_enabled else 'Disabled'}")
        self.status_text.append(f"Export formats: {', '.join(export_formats)}")
        self.status_text.append("=" * 50)

        # Create and start task
        self.current_task = GeometryCalculationTask(
            layers_to_process, buffer_enabled, buffer_distance, output_dir, export_formats
        )
        
        self.current_task.progressChanged.connect(lambda value: self.progress.setValue(int(value)))
        self.current_task.statusUpdate.connect(self.update_status)
        self.current_task.taskCompleted.connect(self.on_task_completed)
        self.current_task.taskTerminated.connect(self.on_task_terminated)
        
        QgsApplication.taskManager().addTask(self.current_task)

    def update_status(self, message):
        """Update status text"""
        if self.status_text:
            self.status_text.append(f"{message}")
            # Auto-scroll to bottom
            scrollbar = self.status_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def cancel_processing(self):
        """Cancel the current processing task"""
        if self.current_task:
            self.current_task.cancel()
            self.update_status("❌ Processing cancelled by user.")

    def on_task_completed(self):
        """Handle task completion"""
        self.run_button.setVisible(True)
        self.cancel_button.setVisible(False)
        
        if self.current_task and self.current_task.error_message:
            QMessageBox.critical(None, "Error", f"Processing failed:\n{self.current_task.error_message}")
            self.update_status(f"ERROR: {self.current_task.error_message}")
        else:
            # Add results to QGIS and calculate totals
            total_original = 0
            total_buffer = 0
            total_area = 0.0
            total_buffer_area = 0.0
            total_length = 0.0
            
            if self.current_task:
                for result in self.current_task.results:
                    if result['original_layer']:
                        QgsProject.instance().addMapLayer(result['original_layer'])
                        total_original += 1
                        self.update_status(f"Added to QGIS: {result['original_layer'].name()}")
                        
                        # Calculate totals from features
                        for feature in result['original_layer'].getFeatures():
                            value = feature['Value'] if feature['Value'] is not None else 0
                            value_type = feature['Value_Type'] or ''
                            buffer_area = feature['Buffer_Area_km2'] if feature['Buffer_Area_km2'] is not None else 0
                            
                            if 'Area' in value_type:
                                total_area += value
                            elif 'Length' in value_type:
                                total_length += value
                            
                            if buffer_area > 0:
                                total_buffer_area += buffer_area
                    
                    if result['buffer_layer']:
                        QgsProject.instance().addMapLayer(result['buffer_layer'])
                        total_buffer += 1
                        self.update_status(f"Added buffer layer: {result['buffer_layer'].name()}")
                    
                    self.update_status(f"CSV saved: {os.path.basename(result['csv_path'])}")
                    
                    for exported_file in result['exported_files']:
                        self.update_status(f"Exported: {os.path.basename(exported_file)}")
            
            # Create comprehensive summary
            summary_lines = [
                "CALCULATION SUMMARY",
                "=" * 30,
                f"Original layers processed: {total_original}",
                f"Buffer layers created: {total_buffer}",
                f"Files exported: {sum(len(r['exported_files']) for r in self.current_task.results) if self.current_task else 0}",
                "",
                "CALCULATED VALUES:",
                "-" * 20
            ]
            
            if total_area > 0:
                summary_lines.append(f"Total Area: {total_area:.4f} km²")
            if total_length > 0:
                summary_lines.append(f"Total Length: {total_length:.4f} km")
            if total_buffer_area > 0:
                summary_lines.append(f"Total Buffer Area: {total_buffer_area:.4f} km²")
            
            summary_lines.extend([
                "",
                f"Output Directory: {self.output_dir_input.text()}",
                "=" * 30
            ])
            
            # Display comprehensive results
            success_message = (
                f"Processing completed successfully!\n\n"
                f"RESULTS SUMMARY:\n"
                f"• Original layers: {total_original}\n"
                f"• Buffer layers: {total_buffer}\n"
                f"• Files exported: {sum(len(r['exported_files']) for r in self.current_task.results) if self.current_task else 0}\n\n"
                f"CALCULATED VALUES:\n"
            )
            
            if total_area > 0:
                success_message += f"• Total Area: {total_area:.4f} km²\n"
            if total_length > 0:
                success_message += f"• Total Length: {total_length:.4f} km\n"
            if total_buffer_area > 0:
                success_message += f"• Total Buffer Area: {total_buffer_area:.4f} km²\n"
            
            success_message += f"\nAll outputs saved to:\n{self.output_dir_input.text()}"
            
            QMessageBox.information(None, "Success!", success_message)
            
            self.iface.messageBar().pushSuccess(
                "Geometry Calc Pro",
                f"Complete! Area: {total_area:.2f} km², Buffer: {total_buffer_area:.2f} km²"
            )
            
            # Add summary to status
            for line in summary_lines:
                self.update_status(line)
        
        self.current_task = None

    def on_task_terminated(self):
        """Handle task termination"""
        self.run_button.setVisible(True)
        self.cancel_button.setVisible(False)
        self.update_status("Processing was terminated.")
        self.current_task = None


# Email automation functions for future Outlook integration
class EmailAutomation:
    """Class for future Outlook integration"""
    
    @staticmethod
    def detect_keywords(email_subject, email_body):
        """Detect geometry calculation keywords in email"""
        keywords = {
            'area': ['area', 'calculate area', 'polygon area', 'surface area'],
            'buffer': ['buffer', 'buffer analysis', 'buffer zone', 'proximity'],
            'length': ['length', 'distance', 'line length', 'perimeter'],
            'geometry': ['geometry', 'spatial analysis', 'gis analysis']
        }
        
        text = f"{email_subject} {email_body}".lower()
        detected = []
        
        for category, terms in keywords.items():
            if any(term in text for term in terms):
                detected.append(category)
        
        return detected
    
    @staticmethod
    def extract_attachments(email):
        """Extract spatial file attachments from email"""
        # This would be implemented with win32com.client for Outlook
        # Placeholder for future implementation
        spatial_extensions = ['.shp', '.kml', '.kmz', '.gpkg', '.geojson']
        attachments = []
        
        # Future: Extract attachments with spatial extensions
        return attachments
    
    @staticmethod
    def generate_response_template(results, keywords):
        """Generate automated response template"""
        template = f"""
        Subject: Geometry Analysis Results - Automated Processing Complete
        
        Dear User,
        
        Your spatial analysis request has been processed automatically.
        
        📊 Analysis Summary:
        - Keywords detected: {', '.join(keywords)}
        - Files processed: {len(results)} layers
        
        📈 Results:
        """
        
        for result in results:
            if result.get('original_layer'):
                layer_name = result['original_layer'].name()
                template += f"\n• {layer_name}: Analysis completed"
                
                if result.get('buffer_layer'):
                    template += f" (with buffer analysis)"
        
        template += """
        
        📎 Attachments:
        - Calculation results (CSV)
        - Geometry files (SHP/KML)
        
        This is an automated response from Geometry Calculator Pro.
        
        Best regards,
        GIS Analysis System
        """
        
        return template
    
    @staticmethod
    def auto_reply_with_attachments(email, results, output_dir):
        """Auto-reply with results (future implementation)"""
        # This would integrate with Outlook COM to send automated replies
        # with calculated results and file attachments
        pass


# Additional utility functions
class GeometryUtils:
    """Utility functions for geometry processing"""
    
    @staticmethod
    def validate_geometry_file(file_path):
        """Validate if file is a valid geometry file"""
        try:
            layer = QgsVectorLayer(file_path, "test", "ogr")
            return layer.isValid() and layer.featureCount() > 0
        except:
            return False
    
    @staticmethod
    def get_file_statistics(file_path):
        """Get basic statistics about the geometry file"""
        try:
            layer = QgsVectorLayer(file_path, "test", "ogr")
            if not layer.isValid():
                return None
                
            stats = {
                'feature_count': layer.featureCount(),
                'geometry_type': QgsWkbTypes.geometryDisplayString(layer.geometryType()),
                'crs': layer.crs().description(),
                'extent': layer.extent().toString()
            }
            return stats
        except:
            return None
    
    @staticmethod
    def create_summary_report(results, output_dir):
        """Create a comprehensive summary report"""
        report_path = os.path.join(output_dir, "analysis_summary_report.txt")
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("GEOMETRY CALCULATOR PRO - ANALYSIS SUMMARY REPORT\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"Generated: {QgsApplication.locale().toString()}\n")
                f.write(f"Total Layers Processed: {len(results)}\n\n")
                
                for i, result in enumerate(results, 1):
                    f.write(f"Layer {i}: {result.get('layer_name', 'Unknown')}\n")
                    f.write("-" * 40 + "\n")
                    
                    if result.get('csv_path'):
                        f.write(f"CSV Output: {os.path.basename(result['csv_path'])}\n")
                    
                    if result.get('exported_files'):
                        f.write("Exported Files:\n")
                        for exported_file in result['exported_files']:
                            f.write(f"  • {os.path.basename(exported_file)}\n")
                    
                    f.write("\n")
                
                f.write("END OF REPORT\n")
                f.write("=" * 60 + "\n")
            
            return report_path
        except Exception as e:
            QgsMessageLog.logMessage(f"Error creating summary report: {str(e)}", "GeometryCalc", Qgis.Warning)
            return None
