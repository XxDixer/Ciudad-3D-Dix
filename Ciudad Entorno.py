"""
Ciudad 3D v3 — Control total con manos (MediaPipe)
===================================================
GESTOS:
  ✋ Mano abierta (4+ dedos)  → ROTACION de cámara orbital (yaw+pitch)
  ☝️  Solo índice extendido    → PANEO clásico (modo anterior)
  🤞 Índice + pulgar (pistola) → DISPARO (proyectil + explosión)
  🤜 Puño cerrado              → ZOOM in/out según posición Y
TECLADO:
  ESC / q  → salir
  r        → resetear cámara
"""
import sys, math, threading, time, random
import cv2
import mediapipe as mp
import numpy as np
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
WIN_W, WIN_H = 1280, 720
TITLE = b"Ciudad 3D v3 - Rotacion + Disparos"

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO COMPARTIDO (cam_lock protege todo)
# ─────────────────────────────────────────────────────────────────────────────
cam_lock = threading.Lock()

# Cámara orbital: distancia fija, yaw (azimuth) y pitch (elevación)
cam = {
    "yaw":          180.0,   # grados  (0..360)
    "pitch":         25.0,   # grados  (5..80)
    "dist":          32.0,   # unidades (10..55)
    "target_x":       0.0,
    "target_y":       1.5,
    "target_z":       0.0,
    # estado de mano
    "hand_detected":  False,
    "gesture":        "none",   # "open"|"index"|"gun"|"fist"
    "finger_x":       0.5,
    "finger_y":       0.5,
    "thumb_x":        0.5,
    "thumb_y":        0.5,
    "shoot_trigger":  False,    # se activa 1 frame al detectar disparo
}

t_start = time.time()
def get_t(): return time.time() - t_start

# ─────────────────────────────────────────────────────────────────────────────
# PROYECTILES y EXPLOSIONES
# ─────────────────────────────────────────────────────────────────────────────
proj_lock   = threading.Lock()
projectiles = []   # cada uno: {x,y,z, vx,vy,vz, born}
explosions  = []   # cada uno: {x,y,z, born, particles:[{dx,dy,dz,color}]}

PROJ_SPEED  = 28.0
PROJ_LIFE   =  3.0
EXPL_LIFE   =  1.2

random.seed(0)

def spawn_projectile():
    """Lanza un proyectil desde la posición de la cámara hacia su target."""
    with cam_lock:
        yaw_r   = math.radians(cam["yaw"])
        pitch_r = math.radians(cam["pitch"])
        dist    = cam["dist"]
        tx, ty, tz = cam["target_x"], cam["target_y"], cam["target_z"]

    # Posición ojo
    ex = tx + dist * math.cos(pitch_r) * math.sin(yaw_r)
    ey = ty + dist * math.sin(pitch_r)
    ez = tz + dist * math.cos(pitch_r) * math.cos(yaw_r)

    # Dirección normalizada hacia target
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    length = math.sqrt(dx*dx + dy*dy + dz*dz) or 1.0
    dx, dy, dz = dx/length, dy/length, dz/length

    with proj_lock:
        projectiles.append({
            "x": ex, "y": ey + 0.3, "z": ez,
            "vx": dx * PROJ_SPEED,
            "vy": dy * PROJ_SPEED,
            "vz": dz * PROJ_SPEED,
            "born": get_t(),
        })

def spawn_explosion(x, y, z):
    parts = []
    for _ in range(60):
        angle_h = random.uniform(0, 2*math.pi)
        angle_v = random.uniform(-math.pi/2, math.pi/2)
        spd     = random.uniform(0.5, 3.5)
        pdx = spd * math.cos(angle_v) * math.cos(angle_h)
        pdy = spd * math.sin(angle_v) + random.uniform(0.5, 2.0)
        pdz = spd * math.cos(angle_v) * math.sin(angle_h)
        r   = random.uniform(0.8, 1.0)
        g   = random.uniform(0.2, 0.6)
        b   = random.uniform(0.0, 0.1)
        parts.append({"dx": pdx, "dy": pdy, "dz": pdz, "color": (r,g,b)})
    with proj_lock:
        explosions.append({"x":x,"y":y,"z":z,"born":get_t(),"particles":parts})

def update_projectiles(t, dt):
    with proj_lock:
        alive = []
        for p in projectiles:
            age = t - p["born"]
            if age > PROJ_LIFE:
                spawn_explosion(p["x"], p["y"], p["z"])
                continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["z"] += p["vz"] * dt
            # Choca con el suelo
            if p["y"] <= 0.2:
                spawn_explosion(p["x"], 0.3, p["z"])
                continue
            alive.append(p)
        projectiles[:] = alive

        dead_e = []
        for e in explosions:
            if t - e["born"] > EXPL_LIFE:
                dead_e.append(e)
        for e in dead_e:
            explosions.remove(e)

def draw_projectiles(t):
    glDisable(GL_LIGHTING)
    with proj_lock:
        for p in projectiles:
            glPushMatrix()
            glTranslatef(p["x"], p["y"], p["z"])
            glColor3f(1.0, 0.8, 0.1)
            glutSolidSphere(0.18, 8, 6)
            # Estela
            age = t - p["born"]
            glColor4f(1.0, 0.4, 0.0, max(0, 0.7 - age))
            glBegin(GL_LINE_STRIP)
            for s in range(6):
                f = s / 5.0
                glVertex3f(p["x"] - p["vx"]*f*0.05,
                           p["y"] - p["vy"]*f*0.05,
                           p["z"] - p["vz"]*f*0.05)
            glEnd()
            glPopMatrix()

        for e in explosions:
            age  = t - e["born"]
            frac = age / EXPL_LIFE
            alpha = max(0.0, 1.0 - frac)
            for part in e["particles"]:
                scale = 1.0 + frac * 2.5
                px = e["x"] + part["dx"] * scale
                py = e["y"] + part["dy"] * scale
                pz = e["z"] + part["dz"] * scale
                r,g,b = part["color"]
                glColor4f(r, g * (1-frac), b, alpha)
                glPushMatrix()
                glTranslatef(px, py, pz)
                glutSolidSphere(0.12 * (1.0 - frac*0.7), 5, 4)
                glPopMatrix()
    glEnable(GL_LIGHTING)

# ─────────────────────────────────────────────────────────────────────────────
# CIUDAD — 30 objetos, 7 tipos
# ─────────────────────────────────────────────────────────────────────────────
CITY_OBJECTS = [
    # HOUSES (8)
    (-12, -9,"house",   0), (-7, -9,"house",   1), (-2, -9,"house",   2),
    (  3, -9,"house",   0), ( 8, -9,"house",   1), (-10,  9,"house",   2),
    (  0,  9,"house",   0), (10,  9,"house",   1),
    # TOWERS (4)
    ( -5,  0,"tower",   0), ( 5,  0,"tower",   1),
    (  0,  5,"tower",   0), (-13, 5,"tower",   1),
    # SNOWMEN (4)
    (-12,  0,"snowman", 0), (12,  0,"snowman", 1),
    (  0, -5,"snowman", 0), (-6,  5,"snowman", 1),
    # PYRAMIDS (4)
    (  7,  6,"pyramid", 0), (-14,-4,"pyramid", 1),
    ( 14, -5,"pyramid", 0), (  0,-14,"pyramid",1),
    # MUSHROOMS (4)
    ( -9, -3,"mushroom",0), ( 9,  3,"mushroom",1),
    ( -3, 12,"mushroom",0), ( 3,-12,"mushroom",1),
    # OBELISKS (3)
    ( 13, -2,"obelisk", 0), (-13, 2,"obelisk", 1), (0, -9,"obelisk",  0),
    # LANTERNS (3)
    ( -4, -6,"lantern", 0), ( 4,  6,"lantern", 1), (-10, 6,"lantern", 0),
]
assert len(CITY_OBJECTS) == 30

# ─────────────────────────────────────────────────────────────────────────────
# ILUMINACION
# ─────────────────────────────────────────────────────────────────────────────
def setup_lighting():
    glEnable(GL_LIGHTING); glEnable(GL_LIGHT0); glEnable(GL_LIGHT1)
    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    glEnable(GL_NORMALIZE); glShadeModel(GL_SMOOTH)
    glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.20,0.20,0.26,1.0])
    glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90,0.84,0.72,1.0])
    glLightfv(GL_LIGHT0, GL_SPECULAR, [0.55,0.50,0.40,1.0])
    glLightfv(GL_LIGHT0, GL_POSITION, [15.0,25.0,10.0,1.0])
    glLightfv(GL_LIGHT1, GL_AMBIENT,  [0.00,0.00,0.00,1.0])
    glLightfv(GL_LIGHT1, GL_DIFFUSE,  [0.12,0.18,0.42,1.0])
    glLightfv(GL_LIGHT1, GL_SPECULAR, [0.08,0.12,0.38,1.0])
    glLightfv(GL_LIGHT1, GL_POSITION, [-20.0,15.0,-15.0,1.0])
    glMaterialfv(GL_FRONT, GL_SPECULAR, [0.5,0.5,0.5,1.0])
    glMaterialf (GL_FRONT, GL_SHININESS, 48.0)

def setup_fog():
    glEnable(GL_FOG); glFogi(GL_FOG_MODE, GL_EXP2)
    glFogfv(GL_FOG_COLOR, [0.03,0.05,0.13,1.0])
    glFogf(GL_FOG_DENSITY, 0.016)
    glHint(GL_FOG_HINT, GL_NICEST)

# ─────────────────────────────────────────────────────────────────────────────
# SUELO
# ─────────────────────────────────────────────────────────────────────────────
def draw_ground(t):
    size = 38
    glDisable(GL_LIGHTING)
    glColor3f(0.09,0.14,0.24)
    glBegin(GL_QUADS)
    glVertex3f(-size,0,-size); glVertex3f(size,0,-size)
    glVertex3f(size,0,size);   glVertex3f(-size,0,size)
    glEnd()
    pulse = 0.16 + 0.06*math.sin(t*0.8)
    glColor3f(pulse, pulse*1.5, pulse*2.4)
    glLineWidth(0.8)
    glBegin(GL_LINES)
    for i in range(-size, size+1, 2):
        glVertex3f(i,0.01,-size); glVertex3f(i,0.01,size)
        glVertex3f(-size,0.01,i); glVertex3f(size,0.01,i)
    glEnd()
    glEnable(GL_LIGHTING)

# ─────────────────────────────────────────────────────────────────────────────
# FIGURAS
# ─────────────────────────────────────────────────────────────────────────────
def draw_house(v=0):
    wc=[(0.85,0.72,0.55),(0.72,0.80,0.90),(0.90,0.82,0.65)][v%3]
    rc=[(0.70,0.20,0.15),(0.25,0.40,0.65),(0.55,0.35,0.20)][v%3]
    glColor3f(*wc)
    glPushMatrix(); glTranslatef(0,1,0); glutSolidCube(2.0); glPopMatrix()
    glColor3f(0.38,0.22,0.08)
    glPushMatrix(); glTranslatef(0,0.6,1.01); glScalef(0.5,0.8,0.01); glutSolidCube(1.0); glPopMatrix()
    glColor3f(0.65,0.88,0.97)
    for dx in (-0.55,0.55):
        glPushMatrix(); glTranslatef(dx,1.2,1.01); glScalef(0.35,0.35,0.01); glutSolidCube(1.0); glPopMatrix()
    glColor3f(*rc)
    apex,base_y,b=(0,3.2,0),2.0,1.05
    glBegin(GL_TRIANGLES)
    glNormal3f(0,.6,.8);  glVertex3f(-b,base_y,b);  glVertex3f(b,base_y,b);  glVertex3f(*apex)
    glNormal3f(0,.6,-.8); glVertex3f(b,base_y,-b);  glVertex3f(-b,base_y,-b);glVertex3f(*apex)
    glNormal3f(-.8,.6,0); glVertex3f(-b,base_y,-b); glVertex3f(-b,base_y,b); glVertex3f(*apex)
    glNormal3f(.8,.6,0);  glVertex3f(b,base_y,b);   glVertex3f(b,base_y,-b); glVertex3f(*apex)
    glEnd()

def draw_snowman(v=0):
    hc=(0.12,0.10,0.08) if v==0 else (0.18,0.08,0.32)
    sc=(0.85,0.12,0.12) if v==0 else (0.10,0.55,0.30)
    glColor3f(0.95,0.95,0.98)
    glPushMatrix(); glTranslatef(0,0.75,0);  glutSolidSphere(0.75,20,16); glPopMatrix()
    glPushMatrix(); glTranslatef(0,1.90,0);  glutSolidSphere(0.55,20,16); glPopMatrix()
    glPushMatrix(); glTranslatef(0,2.80,0);  glutSolidSphere(0.40,20,16); glPopMatrix()
    glColor3f(0.05,0.05,0.05)
    for dx in (-0.14,0.14):
        glPushMatrix(); glTranslatef(dx,2.88,0.36); glutSolidSphere(0.05,8,8); glPopMatrix()
    glColor3f(0.95,0.45,0.05)
    glPushMatrix(); glTranslatef(0,2.78,0.38); glRotatef(-90,1,0,0); glutSolidCone(0.06,0.22,8,4); glPopMatrix()
    glColor3f(*sc)
    glPushMatrix(); glTranslatef(0,2.30,0); glutSolidTorus(0.07,0.52,8,20); glPopMatrix()
    glColor3f(*hc)
    glPushMatrix(); glTranslatef(0,3.18,0)
    glPushMatrix(); glRotatef(-90,1,0,0); glutSolidTorus(0.06,0.46,6,18); glPopMatrix()
    glTranslatef(0,0.02,0); glRotatef(-90,1,0,0)
    gluCylinder(gluNewQuadric(),0.30,0.28,0.45,12,4)
    glPopMatrix()

def draw_tower(v=0):
    wc=(0.50,0.58,0.72) if v==0 else (0.62,0.50,0.42)
    rc=(0.28,0.34,0.48) if v==0 else (0.42,0.28,0.22)
    fl=4+v
    glColor3f(*wc)
    glPushMatrix(); glTranslatef(0,fl,0); glScalef(1.6,fl*2.0,1.6); glutSolidCube(1.0); glPopMatrix()
    glColor3f(0.65,0.88,0.97)
    for row in range(fl):
        for col in (-0.4,0.4):
            glPushMatrix(); glTranslatef(col,0.8+row*2.0,0.81); glScalef(0.28,0.35,0.01); glutSolidCube(1.0); glPopMatrix()
    glColor3f(*rc)
    glPushMatrix(); glTranslatef(0,fl*2.0,0); glScalef(0.15,1.5,0.15); glutSolidCube(1.0); glPopMatrix()

def draw_pyramid(v=0):
    stone=(0.72,0.65,0.48) if v==0 else (0.55,0.70,0.60)
    tip  =(0.95,0.85,0.30) if v==0 else (0.30,0.85,0.95)
    h,b=4.5,2.0
    glColor3f(*stone)
    glBegin(GL_TRIANGLES)
    glNormal3f(0,b,h);  glVertex3f(-b,0,b);  glVertex3f(b,0,b);  glVertex3f(0,h,0)
    glNormal3f(0,b,-h); glVertex3f(b,0,-b);  glVertex3f(-b,0,-b);glVertex3f(0,h,0)
    glNormal3f(-h,b,0); glVertex3f(-b,0,-b); glVertex3f(-b,0,b); glVertex3f(0,h,0)
    glNormal3f(h,b,0);  glVertex3f(b,0,b);   glVertex3f(b,0,-b); glVertex3f(0,h,0)
    glEnd()
    glBegin(GL_QUADS)
    glNormal3f(0,-1,0)
    glVertex3f(-b,0.01,b); glVertex3f(b,0.01,b); glVertex3f(b,0.01,-b); glVertex3f(-b,0.01,-b)
    glEnd()
    glColor3f(*tip)
    glPushMatrix(); glTranslatef(0,h-0.01,0); glRotatef(-90,1,0,0); glutSolidCone(0.22,0.55,8,4); glPopMatrix()

def draw_mushroom(v=0):
    cap=(0.90,0.18,0.12) if v==0 else (0.18,0.55,0.85)
    glColor3f(0.92,0.88,0.80)
    glPushMatrix(); glRotatef(-90,1,0,0)
    gluCylinder(gluNewQuadric(),0.28,0.22,1.6,12,4)
    glPopMatrix()
    glColor3f(*cap)
    glPushMatrix(); glTranslatef(0,1.6,0); glScalef(1,0.55,1); glutSolidSphere(1.1,20,16); glPopMatrix()
    glColor3f(1,1,1)
    for dx,dy,dz in [(0.5,0.4,0.6),(-0.5,0.4,0.6),(0,0.4,-0.7),(0.6,0.4,-0.3),(-0.6,0.4,-0.3)]:
        glPushMatrix(); glTranslatef(dx,1.6+dy*0.55,dz); glutSolidSphere(0.12,8,6); glPopMatrix()

def draw_obelisk(v=0):
    bc=(0.50,0.52,0.58) if v==0 else (0.48,0.42,0.55)
    tc=(0.90,0.80,0.20) if v==0 else (0.20,0.90,0.80)
    glColor3f(*bc)
    glPushMatrix(); glTranslatef(0,3,0); glScalef(0.6,6.0,0.6); glutSolidCube(1.0); glPopMatrix()
    bright=(bc[0]*1.2,bc[1]*1.2,bc[2]*1.2)
    glColor3f(*bright)
    for y in (0.5,3.0,5.5):
        glPushMatrix(); glTranslatef(0,y,0); glScalef(0.75,0.18,0.75); glutSolidCube(1.0); glPopMatrix()
    glColor3f(*tc)
    glPushMatrix(); glTranslatef(0,6.0,0); glRotatef(-90,1,0,0); glutSolidCone(0.33,0.90,8,4); glPopMatrix()

def draw_lantern(v=0, t=0, idx=0):
    glow=0.5+0.5*math.sin(t*2.0+idx*1.5)
    lc=(1.0,0.9*glow,0.2*glow) if v==0 else (0.2*glow,0.8*glow,1.0)
    glColor3f(0.30,0.30,0.35)
    glPushMatrix(); glRotatef(-90,1,0,0)
    gluCylinder(gluNewQuadric(),0.10,0.09,3.2,8,2)
    glPopMatrix()
    glColor3f(0.75,0.70,0.20) if v==0 else glColor3f(0.20,0.60,0.75)
    glPushMatrix(); glTranslatef(0,3.2,0); glScalef(0.6,0.5,0.6); glutSolidCube(1.0); glPopMatrix()
    glColor3f(*lc)
    glPushMatrix(); glTranslatef(0,3.2,0); glutSolidSphere(0.22,10,8); glPopMatrix()
    glColor3f(0.30,0.30,0.35)
    glPushMatrix(); glTranslatef(0,0,0); glScalef(0.3,0.15,0.3); glutSolidCube(1.0); glPopMatrix()

# ─────────────────────────────────────────────────────────────────────────────
# CIUDAD completa
# ─────────────────────────────────────────────────────────────────────────────
def draw_city(t):
    for idx,(ox,oz,tp,v) in enumerate(CITY_OBJECTS):
        glPushMatrix()
        if tp=="snowman":
            lev=0.40*math.sin(t*1.3+idx*0.9)
            glTranslatef(ox,lev,oz); glRotatef(math.degrees(t*0.5+idx*0.4),0,1,0)
        elif tp=="tower":
            glTranslatef(ox,0,oz); glRotatef(math.degrees(t*0.25+idx*1.1),0,1,0)
        elif tp=="house":
            sway=1.2*math.sin(t*0.5+idx*1.3)
            glTranslatef(ox,0,oz); glRotatef(sway,0,1,0)
        elif tp=="pyramid":
            sc=1.0+0.04*math.sin(t*1.8+idx*0.7)
            glTranslatef(ox,0,oz); glRotatef(math.degrees(t*0.2+idx*0.5),0,1,0); glScalef(sc,sc,sc)
        elif tp=="mushroom":
            bounce=0.25*abs(math.sin(t*1.5+idx*1.1))
            glTranslatef(ox,bounce,oz); glRotatef(math.degrees(t*0.35+idx*0.6),0,1,0)
        elif tp=="obelisk":
            tilt=2.0*math.sin(t*0.4+idx*1.7)
            glTranslatef(ox,0,oz); glRotatef(tilt,0,0,1)
        elif tp=="lantern":
            swing=8.0*math.sin(t*0.9+idx*2.1)
            glTranslatef(ox,0,oz); glRotatef(swing,0,0,1)
        else:
            glTranslatef(ox,0,oz)

        if   tp=="house":    draw_house(v)
        elif tp=="snowman":  draw_snowman(v)
        elif tp=="tower":    draw_tower(v)
        elif tp=="pyramid":  draw_pyramid(v)
        elif tp=="mushroom": draw_mushroom(v)
        elif tp=="obelisk":  draw_obelisk(v)
        elif tp=="lantern":  draw_lantern(v,t,idx)
        glPopMatrix()

# ─────────────────────────────────────────────────────────────────────────────
# ESTRELLAS + LUNA
# ─────────────────────────────────────────────────────────────────────────────
random.seed(42)
STARS=[(random.uniform(-90,90),random.uniform(12,90),random.uniform(-90,90)) for _ in range(220)]
random.seed(0)

def draw_stars(t):
    glDisable(GL_LIGHTING); glPointSize(2.0)
    glBegin(GL_POINTS)
    for i,(sx,sy,sz) in enumerate(STARS):
        b=0.6+0.4*math.sin(t*1.5+i*0.37)
        glColor3f(b,b,b*1.05); glVertex3f(sx,sy,sz)
    glEnd()
    glPointSize(1.0); glEnable(GL_LIGHTING)

def draw_moon(t):
    glDisable(GL_LIGHTING)
    glPushMatrix()
    a=t*2.5
    glTranslatef(65*math.cos(math.radians(a)),42,65*math.sin(math.radians(a)))
    glColor3f(0.95,0.92,0.80); glutSolidSphere(5.0,22,18)
    glPopMatrix()
    glEnable(GL_LIGHTING)

# ─────────────────────────────────────────────────────────────────────────────
# CROSSHAIR + HUD
# ─────────────────────────────────────────────────────────────────────────────
shoot_flash = {"active": False, "born": 0.0}

def draw_hud(t):
    with cam_lock:
        hd  = cam["hand_detected"]
        gs  = cam["gesture"]
        fx  = cam["finger_x"]
        fy  = cam["finger_y"]

    glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0,WIN_W,0,WIN_H,-1,1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()

    cx, cy = WIN_W//2, WIN_H//2

    # ── Flash de disparo ──
    flash_age = t - shoot_flash["born"]
    if shoot_flash["active"] and flash_age < 0.12:
        alpha = max(0, 1.0 - flash_age/0.12)
        glColor4f(1.0, 0.5, 0.0, alpha * 0.55)
        glBegin(GL_QUADS)
        glVertex2f(0,0); glVertex2f(WIN_W,0)
        glVertex2f(WIN_W,WIN_H); glVertex2f(0,WIN_H)
        glEnd()
    else:
        shoot_flash["active"] = False

    # ── Crosshair central ──
    gs_colors = {
        "gun":   (1.0,0.2,0.2),
        "open":  (0.2,0.9,0.4),
        "index": (0.2,0.7,1.0),
        "fist":  (1.0,0.7,0.0),
        "none":  (0.7,0.7,0.7),
    }
    cr,cg,cb = gs_colors.get(gs,(0.7,0.7,0.7))
    glColor3f(cr,cg,cb)
    glLineWidth(2.0)
    L=16; G=5
    glBegin(GL_LINES)
    glVertex2f(cx-L,cy); glVertex2f(cx-G,cy)
    glVertex2f(cx+G,cy); glVertex2f(cx+L,cy)
    glVertex2f(cx,cy-L); glVertex2f(cx,cy-G)
    glVertex2f(cx,cy+G); glVertex2f(cx,cy+L)
    glEnd()
    # Circulo pequeño del centro
    glBegin(GL_LINE_LOOP)
    for i in range(20):
        a=2*math.pi*i/20
        glVertex2f(cx+G*math.cos(a), cy+G*math.sin(a))
    glEnd()
    glLineWidth(1.0)

    # ── Panel de gesto (esquina superior izquierda) ──
    gesture_label = {
        "open":  "ROTAR CAMARA",
        "index": "PANEO",
        "gun":   "[ DISPARO LISTO ]",
        "fist":  "ZOOM",
        "none":  "Sin mano",
    }.get(gs,"---")
    panel_col = (0.1,0.8,0.3,0.75) if hd else (0.8,0.1,0.1,0.75)
    glColor4f(*panel_col)
    glBegin(GL_QUADS)
    glVertex2f(8,WIN_H-44); glVertex2f(320,WIN_H-44)
    glVertex2f(320,WIN_H-8); glVertex2f(8,WIN_H-8)
    glEnd()

    # Indicador de posición del dedo (solo si mano detectada)
    if hd:
        px=int(fx*WIN_W); py=int((1-fy)*WIN_H)
        glColor3f(1.0,1.0,0.0); glPointSize(13)
        glBegin(GL_POINTS); glVertex2f(px,py); glEnd()
        glPointSize(1)

    # ── Leyenda (esquina inferior izquierda) ──
    # (Solo marcos de colores, texto no disponible en GLUT puro fácilmente)
    # Los colores indican el gesto activo
    colors_legend=[("gun",(1,0.2,0.2)),("open",(0.2,0.9,0.4)),("index",(0.2,0.7,1)),("fist",(1,0.7,0))]
    for i,(gname,col) in enumerate(colors_legend):
        active = (gs==gname)
        glColor4f(*col, 0.9 if active else 0.35)
        bx=10+i*38; by=10
        glBegin(GL_QUADS)
        glVertex2f(bx,by); glVertex2f(bx+32,by)
        glVertex2f(bx+32,by+22); glVertex2f(bx,by+22)
        glEnd()

    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW);  glPopMatrix()
    glEnable(GL_DEPTH_TEST); glEnable(GL_LIGHTING)

# ─────────────────────────────────────────────────────────────────────────────
# CAMARA ORBITAL
# ─────────────────────────────────────────────────────────────────────────────
def get_eye_pos():
    with cam_lock:
        yaw_r   = math.radians(cam["yaw"])
        pitch_r = math.radians(cam["pitch"])
        dist    = cam["dist"]
        tx,ty,tz= cam["target_x"],cam["target_y"],cam["target_z"]
    ex = tx + dist*math.cos(pitch_r)*math.sin(yaw_r)
    ey = ty + dist*math.sin(pitch_r)
    ez = tz + dist*math.cos(pitch_r)*math.cos(yaw_r)
    return ex,ey,ez, tx,ty,tz

# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────────────────────────────
prev_t = [get_t()]

def display():
    t  = get_t()
    dt = t - prev_t[0]
    prev_t[0] = t

    update_projectiles(t, dt)

    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glLoadIdentity()

    ex,ey,ez,tx,ty,tz = get_eye_pos()
    gluLookAt(ex,ey,ez, tx,ty,tz, 0,1,0)

    glLightfv(GL_LIGHT0, GL_POSITION,[15,25,10,1])
    glLightfv(GL_LIGHT1, GL_POSITION,[-20,15,-15,1])

    draw_stars(t)
    draw_moon(t)
    draw_ground(t)
    draw_city(t)
    draw_projectiles(t)
    draw_hud(t)

    glutSwapBuffers()

def reshape(w,h):
    if h==0: h=1
    glViewport(0,0,w,h)
    glMatrixMode(GL_PROJECTION); glLoadIdentity()
    gluPerspective(60.0,w/h,0.3,280.0)
    glMatrixMode(GL_MODELVIEW)

def timer_cb(v):
    glutPostRedisplay()
    glutTimerFunc(16,timer_cb,0)

def keyboard(key,x,y):
    if key in (b'\x1b',b'q'):
        sys.exit(0)
    elif key==b'r':
        with cam_lock:
            cam["yaw"]=180; cam["pitch"]=25; cam["dist"]=32

# ─────────────────────────────────────────────────────────────────────────────
# OPENGL INIT
# ─────────────────────────────────────────────────────────────────────────────
def init_opengl():
    glClearColor(0.03,0.04,0.13,1.0)
    glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL)
    glHint(GL_PERSPECTIVE_CORRECTION_HINT, GL_NICEST)
    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
    setup_lighting(); setup_fog()

# ─────────────────────────────────────────────────────────────────────────────
# GESTOS (MediaPipe)
# ─────────────────────────────────────────────────────────────────────────────
def finger_extended(lm, tip_id, pip_id):
    """True si la punta está más alta (Y menor en imagen) que el nudillo PIP."""
    return lm[tip_id].y < lm[pip_id].y

def classify_gesture(lm):
    """
    Clasifica la mano en uno de cuatro gestos:
      'gun'   — índice extendido + pulgar extendido, otros doblados  (pistola)
      'open'  — 4 o más dedos extendidos                             (rotar)
      'index' — solo índice extendido                                (paneo)
      'fist'  — todos doblados                                       (zoom)
    """
    # Dedos: 4=meñique, 3=anular, 2=medio, 1=índice, 0=pulgar
    idx   = finger_extended(lm, 8,  6)    # índice
    mid   = finger_extended(lm, 12, 10)   # medio
    ring  = finger_extended(lm, 16, 14)   # anular
    pink  = finger_extended(lm, 20, 18)   # meñique
    # Pulgar: compara X (en imagen espejada, tip más a la derecha = extendido)
    thumb = abs(lm[4].x - lm[2].x) > 0.06

    count = sum([idx, mid, ring, pink])

    if idx and thumb and not mid and not ring and not pink:
        return "gun"
    elif count >= 3:
        return "open"
    elif idx and not mid and not ring and not pink:
        return "index"
    else:
        return "fist"

# ─────────────────────────────────────────────────────────────────────────────
# HILO MEDIAPIPE
# ─────────────────────────────────────────────────────────────────────────────
# Estado previo para detectar flanco de disparo
_prev_gesture   = "none"
_gun_ready_time = 0.0          # tiempo en que entró en gesto gun
GUN_HOLD_MIN    = 0.25          # segundos que hay que mantener "gun" para disparar
_shot_fired     = False         # ya se disparó en esta ráfaga

def mediapipe_thread():
    global _prev_gesture, _gun_ready_time, _shot_fired

    import os, urllib.request
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = "hand_landmarker.task"
    if not os.path.exists(model_path):
        print("[MediaPipe] Descargando modelo...")
        url="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        urllib.request.urlretrieve(url, model_path)
        print("[MediaPipe] Descarga completa.")

    base_opts = python.BaseOptions(model_asset_path=model_path)
    opts = vision.HandLandmarkerOptions(
        base_options=base_opts,
        num_hands=1,
        min_hand_detection_confidence=0.58,
        running_mode=vision.RunningMode.IMAGE)
    lm_detector = vision.HandLandmarker.create_from_options(opts)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 60)

    if not cap.isOpened():
        print("[MediaPipe] No se pudo abrir la cámara."); return

    # Prev finger pos para calcular delta de rotación
    prev_fx, prev_fy = 0.5, 0.5
    first_frame = True

    while True:
        ret, frame = cap.read()
        if not ret: continue

        frame   = cv2.flip(frame, 1)
        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        results = lm_detector.detect(mp_img)

        now = get_t()

        if results.hand_landmarks:
            lm  = results.hand_landmarks[0]
            fx  = lm[8].x    # índice tip X
            fy  = lm[8].y    # índice tip Y
            tx  = lm[4].x    # pulgar tip X
            ty  = lm[4].y    # pulgar tip Y

            gesture = classify_gesture(lm)

            # ── Deltas de movimiento de mano ──
            if first_frame:
                dfx, dfy = 0.0, 0.0
                first_frame = False
            else:
                dfx = fx - prev_fx
                dfy = fy - prev_fy

            with cam_lock:
                cam["hand_detected"] = True
                cam["gesture"]       = gesture
                cam["finger_x"]      = fx
                cam["finger_y"]      = fy
                cam["thumb_x"]       = tx
                cam["thumb_y"]       = ty

                ALPHA = 0.14   # suavizado

                if gesture == "open":
                    # ROTACION orbital: delta X → yaw,  delta Y → pitch
                    cam["yaw"]   = (cam["yaw"]   - dfx * 180.0) % 360.0
                    cam["pitch"] = max(5.0, min(75.0, cam["pitch"] + dfy * 90.0))

                elif gesture == "index":
                    # PANEO clásico (mueve target XZ)
                    new_tx = -18 + fx * 36
                    new_tz = -18 + fy * 36
                    cam["target_x"] = cam["target_x"]*(1-ALPHA) + new_tx*ALPHA
                    cam["target_z"] = cam["target_z"]*(1-ALPHA) + new_tz*ALPHA

                elif gesture == "fist":
                    # ZOOM: posición Y de la mano → distancia
                    new_dist = 12 + fy * 42
                    cam["dist"] = cam["dist"]*(1-ALPHA) + new_dist*ALPHA

            # ── Lógica de disparo ──
            if gesture == "gun":
                if _prev_gesture != "gun":
                    _gun_ready_time = now
                    _shot_fired = False
                elif not _shot_fired and (now - _gun_ready_time) >= GUN_HOLD_MIN:
                    spawn_projectile()
                    shoot_flash["active"] = True
                    shoot_flash["born"]   = now
                    _shot_fired = True
            else:
                _shot_fired = False

            _prev_gesture = gesture
            prev_fx, prev_fy = fx, fy

            # Dibujar overlay en la ventana de cámara
            px,py=int(fx*frame.shape[1]),int(fy*frame.shape[0])
            gest_colors={"gun":(0,50,255),"open":(0,220,80),"index":(255,180,0),"fist":(0,120,255)}
            col=gest_colors.get(gesture,(200,200,200))
            cv2.circle(frame,(px,py),14,col,-1)
            cv2.putText(frame,gesture,(px+16,py-10),cv2.FONT_HERSHEY_SIMPLEX,0.8,(255,255,255),2)

        else:
            with cam_lock:
                cam["hand_detected"] = False
                cam["gesture"]       = "none"
            _prev_gesture = "none"
            first_frame   = True

        small = cv2.resize(frame,(640,360))
        cv2.imshow("MediaPipe — Gestos (q=salir)", small)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("="*62)
    print("  Ciudad 3D v3 — Rotacion + Disparos con gestos de mano")
    print("="*62)
    print("  ✋ Mano abierta  (4 dedos)   → ROTAR camara orbital")
    print("  ☝️  Solo indice               → PANEO del objetivo")
    print("  🤜 Punio cerrado              → ZOOM (Y de la mano)")
    print("  🔫 Indice + pulgar (pistola)  → DISPARO con proyectil")
    print("  r                             → resetear camara")
    print("  ESC / q                       → salir")
    print("="*62)

    t_mp = threading.Thread(target=mediapipe_thread, daemon=True)
    t_mp.start()

    glutInit(sys.argv)
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)
    glutInitWindowSize(WIN_W, WIN_H)
    glutInitWindowPosition(80, 40)
    glutCreateWindow(TITLE)

    init_opengl()
    glutDisplayFunc(display)
    glutReshapeFunc(reshape)
    glutKeyboardFunc(keyboard)
    glutTimerFunc(16, timer_cb, 0)
    glutMainLoop()

if __name__=="__main__":
    main()