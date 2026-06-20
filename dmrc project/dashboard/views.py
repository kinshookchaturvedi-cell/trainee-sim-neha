from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from .models import Layout, Station, Crossover, Depot
import csv
import json
# =====================================================================
# Backend Object-Oriented Design (OOP) for Metro Simulation Elements
# =====================================================================
class TrackCircuit:
    """
    Represents an isolated track segment (Block) that can detect 
    train occupancy. Occupancy drops to 0 when occupied, and picks up to 1 when clear.
    """
    def __init__(self, tc_id, line, start_x, end_x):
        self.tc_id = tc_id          # Unique identifier, e.g. "TC-UP-02"
        self.line = line            # "up", "down", or "crossover"
        self.start_x = start_x      # Left boundary coordinate
        self.end_x = end_x          # Right boundary coordinate
        self.is_occupied = False    # State: False (Pick-up / Clear), True (Drop / Occupied)
    def to_dict(self):
        return {
            'tc_id': self.tc_id,
            'line': self.line,
            'start_x': self.start_x,
            'end_x': self.end_x,
            'is_occupied': self.is_occupied
        }
class PointSwitch:
    """
    Represents physical crossover track switch points. Points guide trains between lines
    and can be set to Normal (straight) or Reverse (diverging).
    """
    def __init__(self, point_id, tc_id, from_station, to_station, position_type, x_left, x_right, y_up, y_down):
        self.point_id = point_id          # Unique identifier, e.g. "P-01"
        self.tc_id = tc_id                # Track Circuit segment the switch sits on
        self.from_station = from_station  # Reference station number
        self.to_station = to_station      # Secondary station number
        self.position_type = position_type# "before" or "after" the station
        self.x_left = x_left              # Left geometric coordinate
        self.x_right = x_right            # Right geometric coordinate
        self.y_up = y_up                  # Y coordinate on UP line
        self.y_down = y_down              # Y coordinate on DOWN line
        self.current_state = 'N'          # State: 'N' (Normal / Straight) or 'R' (Reverse / Diverging)
        self.is_locked = False            # True when a train occupies self.tc_id (cannot switch)
    def to_dict(self):
        return {
            'point_id': self.point_id,
            'tc_id': self.tc_id,
            'from_station': self.from_station,
            'to_station': self.to_station,
            'position_type': self.position_type,
            'x_left': self.x_left,
            'x_right': self.x_right,
            'y_up': self.y_up,
            'y_down': self.y_down,
            'current_state': self.current_state,
            'is_locked': self.is_locked
        }
class SignalPost:
    """
    Represents a physical wayside 3-Aspect Signal (Green, Violet, Red)
    used to protect blocks and crossovers.
    """
    def __init__(self, signal_id, line, x, y, protects_tc_id, signal_type):
        self.signal_id = signal_id        # Unique identifier, e.g. "S-UP-02"
        self.line = line                  # "up" or "down"
        self.x = x                        # Layout X coordinate
        self.y = y                        # Layout Y coordinate
        self.protects_tc_id = protects_tc_id # The track circuit this signal regulates entry to
        self.signal_type = signal_type    # Type: "station" or "crossover"
        self.aspect = 'GREEN'             # Current aspect: 'GREEN', 'VIOLET', 'RED'
    def to_dict(self):
        return {
            'signal_id': self.signal_id,
            'line': self.line,
            'x': self.x,
            'y': self.y,
            'protects_tc_id': self.protects_tc_id,
            'signal_type': self.signal_type,
            'aspect': self.aspect
        }
class MetroNetwork:
    """
    Master container class that reads the database models, builds the track layout,
    instantiates all OOP classes, links signals to blocks, and validates layout interlocking.
    """
    def __init__(self, layout, spacing, up_y, down_y, margin_left, margin_right, svg_width, st_w, st_h):
        self.layout = layout
        self.num_stations = layout.num_stations
        self.spacing = spacing
        self.up_y = up_y
        self.down_y = down_y
        self.margin_left = margin_left
        self.margin_right = margin_right
        self.svg_width = svg_width
        self.st_w = st_w
        self.st_h = st_h
        self.stations = []
        self.track_circuits = []
        self.points = []
        self.signals = []
        self._build_network()
    def _build_network(self):
        # 1. Instantiate Stations
        for i in range(1, self.num_stations + 1):
            x = self.margin_left + (i - 1) * self.spacing
            self.stations.append({
                'number': i,
                'label': f'ST-{i:02d}',
                'x': x,
                'box_x': x - self.st_w // 2,
                'box_up_y': self.up_y - self.st_h // 2,
                'box_down_y': self.down_y - self.st_h // 2,
                'width': self.st_w,
                'height': self.st_h,
                'up_y': self.up_y,
                'down_y': self.down_y,
            })
        # Sort stations from West (left) to East (right)
        sorted_stations = sorted(self.stations, key=lambda s: s['x'])
        # 2. Instantiate Track Circuits (Electrical block partitions)
        # Lead track blocks (before first station platform)
        self.track_circuits.append(TrackCircuit('TC-UP-LEAD', 'up', self.margin_left, sorted_stations[0]['x']))
        self.track_circuits.append(TrackCircuit('TC-DN-LEAD', 'down', self.margin_left, sorted_stations[0]['x']))
        # Platform-to-Platform block sections
        for i in range(len(sorted_stations) - 1):
            s_curr = sorted_stations[i]
            s_next = sorted_stations[i+1]
            self.track_circuits.append(TrackCircuit(f'TC-UP-{i+1}', 'up', s_curr['x'], s_next['x']))
            self.track_circuits.append(TrackCircuit(f'TC-DN-{i+1}', 'down', s_curr['x'], s_next['x']))
        # Trail track blocks (after last station platform)
        last_s = sorted_stations[-1]
        self.track_circuits.append(TrackCircuit('TC-UP-TRAIL', 'up', last_s['x'], self.svg_width - self.margin_right))
        self.track_circuits.append(TrackCircuit('TC-DN-TRAIL', 'down', last_s['x'], self.svg_width - self.margin_right))
        # 3. Instantiate Crossover Points
        XOV_WIDTH = 50
        XOV_DISTANCE = 60
        for idx, co in enumerate(Crossover.objects.filter(layout=self.layout), 1):
            from_x = self.margin_left + (co.from_station - 1) * self.spacing
            if co.position == 'after':
                x_left  = from_x + self.st_w // 2 + XOV_DISTANCE
                x_right = x_left + XOV_WIDTH
            else:
                x_right = from_x - self.st_w // 2 - XOV_DISTANCE
                x_left  = x_right - XOV_WIDTH
            # Crossover turnout orientation direction
            is_last = (co.from_station == self.num_stations or co.to_station == self.num_stations)
            if is_last:
                co_type = 'up_to_down'
            elif co.from_station == 1 or co.to_station == 1:
                co_type = 'down_to_up'
            elif co.from_station < co.to_station:
                co_type = 'up_to_down'
            else:
                co_type = 'down_to_up'
            # Point switch occupies a unique track circuit segment
            point_id = f'P-{idx}'
            tc_id = f'TC-XOV-{idx}'
            self.points.append(PointSwitch(
                point_id=point_id,
                tc_id=tc_id,
                from_station=co.from_station,
                to_station=co.to_station,
                position_type=co.position,
                x_left=x_left,
                x_right=x_right,
                y_up=self.up_y,
                y_down=self.down_y
            ))
            # Register the physical turnout track circuit
            self.track_circuits.append(TrackCircuit(tc_id, 'crossover', x_left, x_right))
        # 4. Instantiate Wayside Signal Posts
        # Station Platform Entry Signals
        for s in self.stations:
            # UP signal protecting the block containing platform 1
            self.signals.append(SignalPost(
                signal_id=f'S-UP-{s["number"]}',
                line='up',
                x=s['box_x'] - 15,
                y=self.up_y,
                protects_tc_id=self._get_tc_at(s['box_x'], 'up'),
                signal_type='station'
            ))
            # DOWN signal protecting the block containing platform 2
            self.signals.append(SignalPost(
                signal_id=f'S-DN-{s["number"]}',
                line='down',
                x=s['box_x'] + s['width'] + 15,
                y=self.down_y,
                protects_tc_id=self._get_tc_at(s['box_x'] + s['width'], 'down'),
                signal_type='station'
            ))
        # Crossover Entry Signals
        for idx, pt in enumerate(self.points, 1):
            if pt.from_station < pt.to_station or pt.from_station == self.num_stations:
                # UP line signal protecting crossover entry
                self.signals.append(SignalPost(
                    signal_id=f'S-CO-{idx}',
                    line='up',
                    x=pt.x_left - 15,
                    y=self.up_y,
                    protects_tc_id=pt.tc_id,
                    signal_type='crossover'
                ))
            else:
                # DOWN line signal protecting crossover entry
                self.signals.append(SignalPost(
                    signal_id=f'S-CO-{idx}',
                    line='down',
                    x=pt.x_right + 15,
                    y=self.down_y,
                    protects_tc_id=pt.tc_id,
                    signal_type='crossover'
                ))
    def _get_tc_at(self, x, line):
        for tc in self.track_circuits:
            if tc.line == line and tc.start_x <= x <= tc.end_x:
                return tc.tc_id
        return 'TC-UNKNOWN'
    def get_serialized_data(self):
        return {
            'stations': self.stations,
            'track_circuits': [tc.to_dict() for tc in self.track_circuits],
            'points': [p.to_dict() for p in self.points],
            'signals': [s.to_dict() for s in self.signals]
        }
# =====================================================================
# Django Controller Views
# =====================================================================
def login_view(request):
    if request.user.is_authenticated:
        return redirect('input')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('input')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'dashboard/login.html')
def logout_view(request):
    logout(request)
    return redirect('login')
@login_required(login_url='login')
def input_view(request):
    if request.method == 'POST':
        try:
            num_stations   = int(request.POST.get('num_stations', 0))
            num_crossovers = int(request.POST.get('num_crossovers', 0))
            num_depots     = int(request.POST.get('num_depots', 0))
            if num_stations < 2:
                messages.error(request, 'You need at least 2 stations.')
                return redirect('input')
            crossover_data = []
            errors = []
            for i in range(1, num_crossovers + 1):
                from_s   = request.POST.get(f'from_station_{i}')
                to_s     = request.POST.get(f'to_station_{i}')
                position = request.POST.get(f'co_position_{i}', 'after')
                if not from_s or not to_s:
                    errors.append(f'Crossover {i}: missing values.')
                    continue
                from_s, to_s = int(from_s), int(to_s)
                if from_s == to_s:
                    errors.append(f'Crossover {i}: from and to cannot be same.')
                elif from_s < 1 or from_s > num_stations:
                    errors.append(f'Crossover {i}: station {from_s} out of range.')
                elif to_s < 1 or to_s > num_stations:
                    errors.append(f'Crossover {i}: station {to_s} out of range.')
                else:
                    crossover_data.append((from_s, to_s, position))
            depot_data = []
            for i in range(1, num_depots + 1):
                near_s   = request.POST.get(f'depot_station_{i}')
                track    = request.POST.get(f'depot_track_{i}', 'up')
                position = request.POST.get(f'depot_position_{i}', 'after')
                if not near_s:
                    errors.append(f'Depot {i}: missing station.')
                    continue
                near_s = int(near_s)
                if near_s < 1 or near_s > num_stations:
                    errors.append(f'Depot {i}: station {near_s} out of range.')
                else:
                    depot_data.append((near_s, track, position))
            if errors:
                for e in errors:
                    messages.error(request, e)
                return redirect('input')
            # Always force a crossover at the last station so the
            # train can reverse direction automatically, even if
            # the user didn't add one near the terminal station.
            last_station = num_stations
            second_last  = num_stations - 1 if num_stations > 1 else num_stations
            already_has_last = any(
                c[0] == last_station or c[1] == last_station for c in crossover_data
            )
            if not already_has_last:
                crossover_data.append((second_last, last_station, 'before'))
                num_crossovers += 1
            layout = Layout.objects.create(
                user=request.user,
                num_stations=num_stations,
                num_crossovers=num_crossovers,
            )
            for idx in range(1, num_stations + 1):
                Station.objects.create(layout=layout, number=idx)
            for from_s, to_s, position in crossover_data:
                Crossover.objects.create(
                    layout=layout,
                    from_station=from_s,
                    to_station=to_s,
                    position=position,
                )
            for near_s, track, position in depot_data:
                Depot.objects.create(
                    layout=layout,
                    near_station=near_s,
                    track=track,
                    position=position,
                )
            request.session['layout_id'] = layout.id
            return redirect('layout')
        except (ValueError, TypeError):
            messages.error(request, 'Please enter valid numbers.')
            return redirect('input')
    return render(request, 'dashboard/input.html')
@login_required(login_url='login')
def layout_view(request):
    layout_id = request.session.get('layout_id')
    if not layout_id:
        messages.error(request, 'No layout found. Please fill the form first.')
        return redirect('input')
    try:
        layout = Layout.objects.get(id=layout_id, user=request.user)
    except Layout.DoesNotExist:
        messages.error(request, 'Layout not found.')
        return redirect('input')
    num_stations = layout.num_stations
    SVG_WIDTH    = 1200
    SVG_HEIGHT   = 400
    MARGIN_LEFT  = 100
    MARGIN_RIGHT = 100
    SPACING      = (SVG_WIDTH - MARGIN_LEFT - MARGIN_RIGHT) // max(num_stations - 1, 1)
    UP_Y         = 120
    DOWN_Y       = 260
    ST_W         = 60
    ST_H         = 24
    # Instantiate the OOP MetroNetwork class to build the layout components
    network = MetroNetwork(
        layout=layout,
        spacing=SPACING,
        up_y=UP_Y,
        down_y=DOWN_Y,
        margin_left=MARGIN_LEFT,
        margin_right=MARGIN_RIGHT,
        svg_width=SVG_WIDTH,
        st_w=ST_W,
        st_h=ST_H
    )
    network_data = network.get_serialized_data()
    # ── depots ─────────────────────────────────────────────────
    depots = []
    DEPOT_LEN = 55
    DEPOT_H   = 45
    CO_OFFSET = 20
    for dp in Depot.objects.filter(layout=layout):
        base_x   = MARGIN_LEFT + (dp.near_station - 1) * SPACING
        branch_x = base_x + CO_OFFSET if dp.position == 'after' else base_x - CO_OFFSET
        track_y  = UP_Y if dp.track == 'up' else DOWN_Y
        direction = -1 if dp.track == 'up' else 1
        end_x = branch_x + DEPOT_LEN
        end_y = track_y + direction * DEPOT_H
        depots.append({
            'near_station': dp.near_station,
            'track':        dp.track,
            'position':     dp.position,
            'x1':           branch_x,
            'y1':           track_y,
            'x2':           end_x,
            'y2':           end_y,
            'label_x':      end_x + 4,
            'label_y':      end_y,
        })
    # Prepare Context dictionary
    context = {
        'layout':     layout,
        'stations':   network_data['stations'],
        'depots':     depots,
        'svg_width':  SVG_WIDTH,
        'svg_height': SVG_HEIGHT,
        'up_y':       UP_Y,
        'down_y':     DOWN_Y,
        'track_x1':   MARGIN_LEFT,
        'track_x2':   SVG_WIDTH - MARGIN_RIGHT,
    }
    context['stations_json'] = json.dumps(network_data['stations'])
    
    # Format crossovers to match frontend key expectations
    frontend_crossovers = []
    for pt in network_data['points']:
        mid_x = (pt['x_left'] + pt['x_right']) // 2
        mid_y = (pt['y_up'] + pt['y_down']) // 2
        frontend_crossovers.append({
            'index':        pt['point_id'].split('-')[1],
            'from_station': pt['from_station'],
            'to_station':   pt['to_station'],
            'position':     pt['position_type'],
            'type':         'up_to_down' if (pt['from_station'] < pt['to_station'] or pt['from_station'] == num_stations) else 'down_to_up',
            'x_left':       pt['x_left'],
            'x_right':      pt['x_right'],
            'width':        pt['x_right'] - pt['x_left'],
            'mid_x':        mid_x,
            'mid_y':        mid_y,
        })
    context['crossovers'] = frontend_crossovers
    context['crossovers_json'] = json.dumps(frontend_crossovers)
    context['last_crossover_x'] = frontend_crossovers[-1]['mid_x'] if frontend_crossovers else None
    # Pass the full network model details to the template as a JSON string
    context['network_json'] = json.dumps(network_data)
    return render(request, 'dashboard/layout.html', context)
@login_required(login_url='login')
def export_csv(request):
    layout_id = request.session.get('layout_id')
    if not layout_id:
        return redirect('input')
    try:
        layout = Layout.objects.get(id=layout_id, user=request.user)
    except Layout.DoesNotExist:
        return redirect('input')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="dmrc_layout_{layout.id}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Type', 'Detail 1', 'Detail 2', 'Position'])
    for s in Station.objects.filter(layout=layout).order_by('number'):
        writer.writerow(['Station', s.number, '', ''])
    for co in Crossover.objects.filter(layout=layout):
        writer.writerow(['Crossover', co.from_station, co.to_station, co.position])
    for dp in Depot.objects.filter(layout=layout):
        writer.writerow(['Depot', dp.near_station, dp.track, dp.position])
    return response
# =====================================================================
# Real-Time Python Simulation Engine & Kinematics Loop
# =====================================================================
import math
import time
def build_journey_path(margin_left, margin_right, spacing, num_stations, up_y, down_y, crossovers, svg_width):
    """
    Builds the closed-loop path segments that the train follows.
    """
    path = []
    sorted_co = sorted(crossovers, key=lambda c: c['x_left'])
    first_co = sorted_co[0] if sorted_co else None
    last_co = sorted_co[-1] if sorted_co else None
    track_x1 = margin_left
    track_x2 = svg_width - margin_right
    if first_co and last_co and first_co['x_left'] != last_co['x_left']:
        path.append({'x1': first_co['x_right'], 'y1': up_y, 'x2': last_co['x_left'], 'y2': up_y, 'track': 'up'})
        path.append({'x1': last_co['x_left'], 'y1': up_y, 'x2': last_co['x_right'], 'y2': down_y, 'track': 'crossover', 'index': last_co['index']})
        path.append({'x1': last_co['x_right'], 'y1': down_y, 'x2': first_co['x_left'], 'y2': down_y, 'track': 'down'})
        path.append({'x1': first_co['x_left'], 'y1': down_y, 'x2': first_co['x_right'], 'y2': up_y, 'track': 'crossover', 'index': first_co['index']})
    elif last_co:
        path.append({'x1': track_x1, 'y1': up_y, 'x2': last_co['x_left'], 'y2': up_y, 'track': 'up'})
        path.append({'x1': last_co['x_left'], 'y1': up_y, 'x2': last_co['x_right'], 'y2': down_y, 'track': 'crossover', 'index': last_co['index']})
        path.append({'x1': last_co['x_right'], 'y1': down_y, 'x2': track_x1, 'y2': down_y, 'track': 'down'})
        path.append({'x1': track_x1, 'y1': down_y, 'x2': track_x1, 'y2': up_y, 'track': 'crossover', 'index': None})
    else:
        path.append({'x1': track_x1, 'y1': up_y, 'x2': track_x2, 'y2': up_y, 'track': 'up'})
        path.append({'x1': track_x2, 'y1': up_y, 'x2': track_x2, 'y2': down_y, 'track': 'crossover', 'index': None})
        path.append({'x1': track_x2, 'y1': down_y, 'x2': track_x1, 'y2': down_y, 'track': 'down'})
        path.append({'x1': track_x1, 'y1': down_y, 'x2': track_x1, 'y2': up_y, 'track': 'crossover', 'index': None})
    for seg in path:
        seg['length'] = math.hypot(seg['x2'] - seg['x1'], seg['y2'] - seg['y1'])
    return path
class Train:
    """
    Models physical train movement parameters and kinematics math.
    """
    def __init__(self, train_id, journey):
        self.train_id = train_id
        self.journey = journey
        self.seg_index = 0
        self.seg_progress = 0.0
        self.speed = 0.0
        self.acc = 0.0
        self.state = 'ACCELERATING'
        self.dwell_timer = 0.0
        self.x = journey[0]['x1']
        self.y = journey[0]['y1']
        self.last_stopped_station = None
        self.last_stopped_line = None
    def get_speed_kmh(self):
        return self.speed * 3.6
    def calculate_acceleration(self):
        speed_kmh = self.get_speed_kmh()
        if speed_kmh < 30:
            return 1.3
        elif speed_kmh < 45:
            return 1.2
        else:
            return 1.0
    def to_dict(self):
        return {
            'train_id': self.train_id,
            'seg_index': self.seg_index,
            'seg_progress': self.seg_progress,
            'speed': self.speed,
            'acc': self.acc,
            'state': self.state,
            'dwell_timer': self.dwell_timer,
            'x': self.x,
            'y': self.y,
            'last_stopped_station': self.last_stopped_station,
            'last_stopped_line': self.last_stopped_line
        }
    @classmethod
    def from_dict(cls, data, journey):
        t = cls(data['train_id'], journey)
        t.seg_index = data['seg_index']
        t.seg_progress = data['seg_progress']
        t.speed = data['speed']
        t.acc = data['acc']
        t.state = data['state']
        t.dwell_timer = data['dwell_timer']
        t.x = data['x']
        t.y = data['y']
        t.last_stopped_station = data['last_stopped_station']
        t.last_stopped_line = data['last_stopped_line']
        return t
class TrainSimEngine:
    """
    Python Simulation Engine running occupancy, speed, and safety interlocking checks.
    """
    def __init__(self, network_data, journey):
        self.stations = network_data['stations']
        self.track_circuits = [TrackCircuit(tc['tc_id'], tc['line'], tc['start_x'], tc['end_x']) for tc in network_data['track_circuits']]
        self.points = [PointSwitch(p['point_id'], p['tc_id'], p['from_station'], p['to_station'], p['position_type'], p['x_left'], p['x_right'], p['y_up'], p['y_down']) for p in network_data['points']]
        self.signals = [SignalPost(s['signal_id'], s['line'], s['x'], s['y'], s['protects_tc_id'], s['signal_type']) for s in network_data['signals']]
        self.journey = journey
        self.train = Train('TR-0011', journey)
    def to_dict(self):
        return {
            'train': self.train.to_dict(),
            'track_circuits': [tc.to_dict() for tc in self.track_circuits],
            'points': [p.to_dict() for p in self.points],
            'signals': [s.to_dict() for s in self.signals]
        }
    @classmethod
    def from_dict(cls, data, network_data, journey):
        engine = cls(network_data, journey)
        engine.train = Train.from_dict(data['train'], journey)
        for tc_data, tc in zip(data['track_circuits'], engine.track_circuits):
            tc.is_occupied = tc_data['is_occupied']
        for p_data, p in zip(data['points'], engine.points):
            p.current_state = p_data['current_state']
            p.is_locked = p_data['is_locked']
        for s_data, s in zip(data['signals'], engine.signals):
            s.aspect = s_data['aspect']
        return engine
    def tick(self, dt):
        t = self.train
        current_seg = self.journey[t.seg_index]
        speed_limit = (25.0 / 3.6) if current_seg['track'] == 'crossover' else (60.0 / 3.6)
        if t.state == 'DWELLING':
            t.speed = 0.0
            t.acc = 0.0
            t.dwell_timer -= dt
            if t.dwell_timer <= 0.0:
                t.state = 'ACCELERATING'
            return
        # 1. Locate next station target stop on the current segment
        stop_target_dist = None
        target_station_obj = None
        if current_seg['track'] == 'up':
            valid_stations = [s for s in self.stations if current_seg['x1'] < s['x'] <= current_seg['x2']]
            valid_stations.sort(key=lambda s: s['x'])
            for s in valid_stations:
                d_station = s['x'] - current_seg['x1']
                if d_station > t.seg_progress + 1.0 and (t.last_stopped_station != s['number'] or t.last_stopped_line != 'up'):
                    stop_target_dist = d_station
                    target_station_obj = s
                    break
        elif current_seg['track'] == 'down':
            valid_stations = [s for s in self.stations if current_seg['x2'] <= s['x'] < current_seg['x1']]
            valid_stations.sort(key=lambda s: s['x'], reverse=True)
            for s in valid_stations:
                d_station = current_seg['x1'] - s['x']
                if d_station > t.seg_progress + 1.0 and (t.last_stopped_station != s['number'] or t.last_stopped_line != 'down'):
                    stop_target_dist = d_station
                    target_station_obj = s
                    break
        # 2. Deceleration zones
        if stop_target_dist is not None:
            dist_to_station = stop_target_dist - t.seg_progress
            brake_dist = (t.speed * t.speed) / (2.0 * 1.2)
            if dist_to_station <= brake_dist + 2.0:
                t.state = 'BRAKING'
                t.acc = - (t.speed * t.speed) / (2.0 * max(1.0, dist_to_station))
                if t.acc > -0.2:
                    t.acc = -1.2
            
            if dist_to_station < 1.5 and t.speed < 1.2:
                t.speed = 0.0
                t.seg_progress = stop_target_dist
                t.state = 'DWELLING'
                t.dwell_timer = 3.0
                t.last_stopped_station = target_station_obj['number']
                t.last_stopped_line = current_seg['track']
                
                self.evaluate_interlocking(target_station_obj['x'], current_seg['track'])
                return
        else:
            # Slow down for crossover speed caution
            next_seg = self.journey[(t.seg_index + 1) % len(self.journey)]
            if next_seg and next_seg['track'] == 'crossover' and t.speed > (25.0 / 3.6):
                dist_to_crossover = current_seg['length'] - t.seg_progress
                slow_dist = (t.speed * t.speed - (25.0/3.6)**2) / (2.0 * 1.2)
                if dist_to_crossover <= slow_dist + 2.0:
                    t.state = 'BRAKING'
                    t.acc = - (t.speed * t.speed - (25.0/3.6)**2) / (2.0 * max(1.0, dist_to_crossover))
                    if t.acc > -0.2:
                        t.acc = -1.2
        # 3. Kinematics updates
        if t.state == 'ACCELERATING':
            t.acc = t.calculate_acceleration()
            t.speed += t.acc * dt
            if t.speed >= speed_limit:
                t.speed = speed_limit
                t.state = 'CRUISING'
                t.acc = 0.0
        elif t.state == 'CRUISING':
            t.acc = 0.0
            if t.speed < speed_limit:
                t.state = 'ACCELERATING'
            else:
                t.speed = speed_limit
        elif t.state == 'BRAKING':
            t.speed += t.acc * dt
            if t.speed < 0.0:
                t.speed = 0.0
        # 4. Progress coordinate update
        t.seg_progress += t.speed * dt
        if t.seg_progress >= current_seg['length']:
            t.seg_progress = t.seg_progress - current_seg['length']
            t.seg_index = (t.seg_index + 1) % len(self.journey)
            t.state = 'ACCELERATING'
        next_seg_active = self.journey[t.seg_index]
        progress_ratio = (t.seg_progress / next_seg_active['length']) if next_seg_active['length'] > 0 else 1.0
        t.x = next_seg_active['x1'] + (next_seg_active['x2'] - next_seg_active['x1']) * progress_ratio
        t.y = next_seg_active['y1'] + (next_seg_active['y2'] - next_seg_active['y1']) * progress_ratio
        # 5. Run interlocking
        self.evaluate_interlocking(t.x, next_seg_active['track'])
    def evaluate_interlocking(self, train_x, train_line):
        # Reset occupancy
        for tc in self.track_circuits:
            tc.is_occupied = False
        # Detect active track circuit block
        active_tc = None
        for tc in self.track_circuits:
            if tc.line == train_line:
                min_x = min(tc.start_x, tc.end_x)
                max_x = max(tc.start_x, tc.end_x)
                if min_x <= train_x <= max_x:
                    tc.is_occupied = True
                    active_tc = tc
        # Lock point switches (Track Locking)
        for pt in self.points:
            if pt.tc_id == (active_tc.tc_id if active_tc else None):
                pt.is_locked = True
            else:
                pt.is_locked = False
        # Cascade Signal Aspects
        for sig in self.signals:
            sig.aspect = 'GREEN'
        if train_line == 'up':
            up_sigs = sorted([s for s in self.signals if s.line == 'up'], key=lambda s: s.x)
            passed_idx = -1
            for i in range(len(up_sigs)):
                if train_x >= up_sigs[i].x:
                    passed_idx = i
            if passed_idx != -1:
                up_sigs[passed_idx].aspect = 'RED'
                if passed_idx > 0:
                    up_sigs[passed_idx - 1].aspect = 'VIOLET'
            next_idx = passed_idx + 1
            if next_idx < len(up_sigs):
                next_sig = up_sigs[next_idx]
                if next_sig.signal_type == 'crossover':
                    next_sig.aspect = 'VIOLET'
        elif train_line == 'down':
            dn_sigs = sorted([s for s in self.signals if s.line == 'down'], key=lambda s: s.x, reverse=True)
            passed_idx = -1
            for i in range(len(dn_sigs)):
                if train_x <= dn_sigs[i].x:
                    passed_idx = i
            if passed_idx != -1:
                dn_sigs[passed_idx].aspect = 'RED'
                if passed_idx > 0:
                    dn_sigs[passed_idx - 1].aspect = 'VIOLET'
            next_idx = passed_idx + 1
            if next_idx < len(dn_sigs):
                next_sig = dn_sigs[next_idx]
                if next_sig.signal_type == 'crossover':
                    next_sig.aspect = 'VIOLET'
        elif train_line == 'crossover':
            current_seg = self.journey[self.train.seg_index]
            if current_seg and current_seg['index'] is not None:
                co_sig = next((s for s in self.signals if s.signal_type == 'crossover' and s.signal_id.endswith(str(current_seg['index']))), None)
                if co_sig:
                    co_sig.aspect = 'RED'
                    line_sigs = sorted([s for s in self.signals if s.line == co_sig.line], key=lambda s: s.x if co_sig.line == 'up' else -s.x)
                    try:
                        idx = line_sigs.index(co_sig)
                        if idx > 0:
                            line_sigs[idx - 1].aspect = 'VIOLET'
                    except ValueError:
                        pass
@login_required(login_url='login')
def simulation_tick(request):
    """
    Simulation tick AJAX endpoint. Updates the physics, occupancy, interlocking,
    and signals on the backend, saving state in the session and returning JSON.
    """
    layout_id = request.session.get('layout_id')
    if not layout_id:
        return HttpResponse('No layout found', status=400)
    try:
        layout = Layout.objects.get(id=layout_id, user=request.user)
    except Layout.DoesNotExist:
        return HttpResponse('Layout not found', status=404)
    num_stations = layout.num_stations
    SVG_WIDTH    = 1200
    SVG_HEIGHT   = 400
    MARGIN_LEFT  = 100
    MARGIN_RIGHT = 100
    SPACING      = (SVG_WIDTH - MARGIN_LEFT - MARGIN_RIGHT) // max(num_stations - 1, 1)
    UP_Y         = 120
    DOWN_Y       = 260
    ST_W         = 60
    ST_H         = 24
    network = MetroNetwork(layout, SPACING, UP_Y, DOWN_Y, MARGIN_LEFT, MARGIN_RIGHT, SVG_WIDTH, ST_W, ST_H)
    network_data = network.get_serialized_data()
    # Reconstruct crossovers to have index
    frontend_crossovers = []
    for pt in network_data['points']:
        mid_x = (pt['x_left'] + pt['x_right']) // 2
        mid_y = (pt['y_up'] + pt['y_down']) // 2
        frontend_crossovers.append({
            'index':        int(pt['point_id'].split('-')[1]),
            'x_left':       pt['x_left'],
            'x_right':      pt['x_right'],
            'mid_x':        mid_x,
            'mid_y':        mid_y,
        })
    journey = build_journey_path(MARGIN_LEFT, MARGIN_RIGHT, SPACING, num_stations, UP_Y, DOWN_Y, frontend_crossovers, SVG_WIDTH)
    # Load simulation state from session
    sim_data = request.session.get('sim_state')
    if not sim_data:
        engine = TrainSimEngine(network_data, journey)
    else:
        try:
            engine = TrainSimEngine.from_dict(sim_data, network_data, journey)
        except Exception:
            engine = TrainSimEngine(network_data, journey)
    # Compute actual delta-time
    last_tick_time = request.session.get('last_tick_time')
    now = time.time()
    if last_tick_time:
        dt = now - last_tick_time
        # Cap dt to avoid speed jump
        if dt > 0.1:
            dt = 0.033
    else:
        dt = 0.033
    request.session['last_tick_time'] = now
    # Execute simulation tick
    engine.tick(dt)
    # Save state back to session
    request.session['sim_state'] = engine.to_dict()
    from django.http import JsonResponse
    return JsonResponse(engine.to_dict())
