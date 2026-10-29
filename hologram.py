import sys
from PyQt6.QtWidgets import QApplication, QWidget, QLineEdit
from PyQt6.QtCore import Qt, QTimer, QPointF, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

class HologramUI(QWidget):
    def __init__(self):
        super().__init__()
        
        # 1. True Transparent, Frameless Window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(800, 800)
        
        self.angle = 0
        self.jarvis_state = "standby"
        
        # 2. Animation for Smooth Fade In/Out (Diffuse effect)
        self.anim_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.anim_opacity.setDuration(1000)
        self.anim_opacity.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        # 3. Holographic Text Input
        self.text_input = QLineEdit(self)
        self.text_input.setPlaceholderText("Type command, Sir...")
        self.text_input.setGeometry(200, 650, 400, 50)
        self.text_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(0, 0, 0, 150);
                color: #00ffff;
                border: 2px solid #00ffff;
                border-radius: 5px;
                padding: 5px;
                font-family: Consolas;
                font-size: 14px;
            }
        """)
        self.text_input.hide()
        self.text_input.returnPressed.connect(self.on_text_submit)
        
        self.on_submit_callback = None
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)

    def on_text_submit(self):
        text = self.text_input.text().strip()
        if text and self.on_submit_callback:
            self.text_input.clear()
            self.on_submit_callback(text)

    def update_animation(self):
        self.angle = (self.angle + 2) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        
        if self.jarvis_state == "speaking":
            color = QColor(255, 170, 0, 220) # Orange
        elif self.jarvis_state == "listening":
            color = QColor(0, 255, 255, 220) # Cyan
        else:
            color = QColor(0, 150, 150, 150) # Dim Cyan (Standby)
            
        painter.setPen(QPen(color, 3))
        painter.save()
        painter.translate(center)
        
        # Inner Ring
        painter.rotate(self.angle)
        painter.drawArc(-100, -100, 200, 200, 0, 270 * 16)
        
        # Middle Ring
        painter.rotate(-self.angle * 2)
        painter.setPen(QPen(color, 2))
        for i in range(0, 360, 30):
            painter.drawArc(-150, -150, 300, 300, i * 16, 15 * 16)
            
        # Outer Ring
        painter.rotate(self.angle * 3)
        painter.setPen(QPen(color, 4))
        for i in range(0, 360, 45):
            painter.drawArc(-200, -200, 400, 400, i * 16, 30 * 16)
            
        painter.restore()
        
        painter.setPen(color)
        painter.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        text = "SYSTEMS STANDBY"
        if self.jarvis_state == "listening": text = "LISTENING..."
        if self.jarvis_state == "speaking": text = "PROCESSING..."
        if self.jarvis_state == "waiting": text = ""
        
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def set_state(self, state):
        self.jarvis_state = state
        if state == "waiting":
            self.anim_opacity.setStartValue(self.windowOpacity())
            self.anim_opacity.setEndValue(0.0)
            self.anim_opacity.start()
            self.text_input.hide()
        else:
            if self.windowOpacity() < 0.1:
                self.anim_opacity.setStartValue(0.0)
                self.anim_opacity.setEndValue(1.0)
                self.anim_opacity.start()
            self.update()

    def show_text_mode(self):
        self.text_input.show()
        self.text_input.setFocus()

    def hide_text_mode(self):
        self.text_input.hide()

    def fade_out_and_close(self):
        """Smoothly fades the window to 0 opacity and then closes it."""
        self.anim_opacity.setStartValue(self.windowOpacity())
        self.anim_opacity.setEndValue(0.0)
        # This ensures the app actually closes after the animation ends
        self.anim_opacity.finished.connect(self.close)
        self.anim_opacity.start()

    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        delta = QPoint(event.globalPosition().toPoint() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()