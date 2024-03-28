#!/usr/bin/python

# speedometer.py
# Copyright (C) 2001-2012  Ian Ward
#
# This module is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.

import time
import sys
import os
import string
import math
import re
import psutil
import threading
import subprocess
import select
import pkg_resources

try:
    __version__ = pkg_resources.get_distribution('speedometer').version
except pkg_resources.DistributionNotFound:
    # Not installed yet.
    __version__ = 'develop'

__usage__ = """Usage: speedometer [options] tap [[-c] tap]...
Monitor network traffic or speed/progress of a file transfer.  At least one
tap must be entered.  -c starts a new column, otherwise taps are piled
vertically.

Taps:
  -f filename [size]          display download speed [with progress bar]
  -r network-interface        display bytes received on network-interface
  -t network-interface        display bytes transmitted on network-interface
  -d command                  display bytes received from running shell command standard output
  -c                          start a new column for following tap arguments

Options:
  -b                          use old blocky display instead of smoothed
                              display even when UTF-8 encoding is detected
                              (use this if you see strange characters)
  -i interval-in-seconds      eg. "5" or "0.25"   default: "1"
  -k (1|16|88|256)            set the number of colors this terminal
                              supports (default 16)
  -l                          use linear charts instead of logarithmic
                              you will VERY LIKELY want to set -m as well
  -m chart-maximum            set the maximum bytes/second displayed on
                              the chart (default 2^32)
  -n chart-minimum            set the minimum bytes/second displayed on
                              the chart (default 32)
  -p                          use original plain-text display (one tap only)
                              default is Yes if data source is from standard input
  -s                          use bits/s instead of bytes/s
  -x                          exit when files reach their expected size
  -z                          report zero size on files that don't exist
                              instead of waiting for them to be created

Note: -rx and -tx are accepted as aliases for -r and -t for compatibility
with earlier releases of speedometer.  -f may be also omitted for similar
reasons.
"""

__urwid_info__ = """
Speedometer requires Urwid 0.9.9.1 or later when not using plain-text display.
Urwid may be downloaded from:  http://excess.org/urwid/
Urwid may be installed system-wide or in the same directory as speedometer.
"""

INITIAL_DELAY = 0.5 # seconds
INTERVAL_DELAY = 1.0 # seconds

VALID_NUM_COLORS = (1, 16, 88, 256)

# FIXME: these globals are becoming a pain
# time for more encapsulation, maybe even per-chart settings?

logarithmic_scale = True
units_per_second = 'bytes'
chart_minimum = 2**5
chart_maximum = 2**32


graph_scale = None
def update_scale():
    """
    parse_args has set chart min/max, units_per_second and logarithmic_scale
    use those settings to generate a scale of values for the LHS of the graph
    """
    global graph_scale
    if logarithmic_scale:
        # be lazy and just use the same scale we always have
        predefined = {
            'bytes': [
                (2**10,  ' 1KiB\n  /s'),
                (2**15, '32KiB\n  /s'),
                (2**20, ' 1MiB\n  /s'),
                (2**25, '32MiB\n  /s'),
                (2**30, ' 1GiB\n  /s'),
            ], 'bits': [
                (2**7,  ' 1Kib\n  /s'),
                (2**12,  '32Kib\n  /s'),
                (2**17, ' 1Mib\n  /s'),
                (2**22, '32Mib\n  /s'),
                (2**27, ' 1Gib\n  /s'),
            ]}
        graph_scale = [(s, label) for s, label in
            predefined[units_per_second] if chart_minimum < s < chart_maximum]
        return

    # linear, we need to generate one
    granularity = math.log(graph_range(), 2)
    granularity -= 2 # magic number, creates at least 4 lines on the scale
    granularity = 2**int(granularity) # only want proper powers of two

    n, r = divmod(chart_minimum, granularity)
    n = n * granularity + (granularity if r else 0)
    graph_scale = []
    while n < chart_maximum:
        graph_scale.append((n, readable_speed(n)))
        n += granularity



def graph_min():
    return math.log(chart_minimum,2) if logarithmic_scale else chart_minimum

def graph_max():
    return math.log(chart_maximum,2) if logarithmic_scale else chart_maximum

def graph_range(): return graph_max() - graph_min()

def graph_lines_captions():
    s = graph_scale
    if logarithmic_scale:
        s = [(math.log(x, 2), cap) for x, cap in s]
        # XXX: quick hack to make this work like it used to
        delta = graph_min()
        s = [(x - delta, cap) for x, cap in s]
    return list(reversed(s))

def graph_lines(): return [x[0] for x in graph_lines_captions()]

URWID_IMPORTED = False
URWID_UTF8 = False
try:
    import urwid
    if urwid.VERSION >= (0, 9, 9, 1):
        URWID_IMPORTED = True
        URWID_UTF8 = urwid.get_encoding_mode() == "utf8"
except (ImportError, AttributeError):
    pass


class Speedometer:
    def __init__(self,maxlog=5):
        """speedometer(maxlog=5)
        maxlog is the number of readings that will be stored"""
        self.log = []
        self.start = None
        self.maxlog = maxlog

    def get_log(self):
        return self.log

    def update(self, bytes):
        """update(bytes) => None
        add a byte reading to the log"""
        t = time.time()
        reading = (t,bytes)
        if not self.start: self.start = reading
        self.log.append(reading)
        self.log = self.log[ - (self.maxlog+1):]

    def delta(self, readings=0, skip=0):
        """delta(readings=0) -> time passed, byte increase
        if readings is 0, time since start is given
        don't include the last 'skip' readings
        None is returned if not enough data available"""
        assert readings >= 0
        assert readings <= self.maxlog, "Log is not long enough to satisfy request"
        assert skip >= 0
        if skip > 0: assert readings > 0, "Can't skip when reading all"

        if skip > len(self.log)-1: return # not enough data
        current = self.log[-1 -skip]

        target = None
        if readings == 0: target = self.start
        elif len(self.log) > readings+skip:
            target = self.log[-(readings+skip+1)]
        if not target: return  # not enough data

        if target == current: return
        byte_increase = current[1]-target[1]
        time_passed = current[0]-target[0]
        return time_passed, byte_increase

    def speed(self, *l, **d):
        d = self.delta(*l, **d)
        if d:
            return delta_to_speed(d)


class EndOfData(Exception):
    pass

class MultiGraphDisplay(object):
    def __init__(self, cols, urwid_ui, exit_on_complete, shiny_colors):
        smoothed = urwid_ui == "smoothed"
        self.displays = []
        l = []
        for c in cols:
            a = []
            for tap in c:
                if tap.ftype == 'file_exp':
                    d = GraphDisplayProgress(tap, smoothed)
                else:
                    d = GraphDisplay(tap, smoothed)
                if shiny_colors:
                    d = ShinyMap(d, shiny_colors)
                a.append(d)
                self.displays.append(d)
            l.append(a)

        graphs = urwid.Columns([urwid.Pile(a) for a in l], 1)
        graphs = urwid.AttrWrap(graphs, 'background')
        title = urwid.Text(" Speedometer "+__version__)
        title = urwid.AttrWrap(urwid.Filler(title), 'title')
        self.top = urwid.Overlay(title, graphs,
            ('fixed left', 5), 17, ('fixed top', 0), 1)

        self.urwid_ui = urwid_ui
        self.exit_on_complete = exit_on_complete

    palette = [
        # name,        16-color fg, bg,         mono fg,    88/256-color fg, bg
        # main bar graph
        ('background', 'dark gray', '',         '',         'g20', 'g70'),
        ('bar:top',    'dark cyan', '',         '',         '#488', ''),
        ('bar',        '',          'dark cyan','standout', '',     '#488'),
        ('bar:num',    '',          '',         '',         '#066', 'g70'),
        # latest "curved" + average bar graph at right side
        ('ca:background', '',       '',         '',         '',     ''),
        ('ca:c:top',   'dark blue', '',         '',         '#66d', ''),
        ('ca:c',       '',          'dark blue','standout', '',     '#66d'),
        ('ca:c:num',   'light blue','',         '',         '#006', 'g70'),
        ('ca:a:top',   'light gray','',         '',         '#6b6', ''),
        ('ca:a',       '',          'light gray','standout','',     '#6b6'),
        ('ca:a:num',   'light gray','',          'bold',    '#060', 'g70'),
        # text headings and numeric values displayed
        ('title',      '',          '',   'underline,bold', '#fff,bold', '#488'),
        ('reading',    '',          '',         '',         '#886', 'g70'),
        # progress bar
        ('pr:n',       '',          'dark blue','',         'g11', '#bb6'),
        ('pr:c',       '',          'dark green','standout','g11', '#fd0'),
        ('pr:cn',      'dark green','dark blue','',         '#fd0', '#bb6'),
        ]


    def main(self, num_colors):
        self.loop = urwid.MainLoop(self.top, palette=self.palette, unhandled_input=self.unhandled_input)
        self.loop.screen.set_terminal_properties(colors=num_colors)

        try:
            pending = self.update_readings()
            if self.exit_on_complete and pending == 0: return
        except EndOfData:
            return
        time.sleep(INITIAL_DELAY)
        self.update_callback()
        self.loop.run()

    def unhandled_input(self, key):
        "Exit on Q or ESC"
        if key in ('q', 'Q', 'esc'):
            SubprocessJobQueue.stop_all_job()
            StdinJobQueue.stop_all_job()
            raise urwid.ExitMainLoop()

    def update_callback(self, *args):
        next_call_in = INTERVAL_DELAY
        if isinstance(time, SimulatedTime):
            next_call_in = 0
            time.sleep(INTERVAL_DELAY) # update simulated time

        self.loop.set_alarm_in(next_call_in, self.update_callback)
        try:
            pending = self.update_readings()
            if self.exit_on_complete and pending == 0: return
        except EndOfData:
            self.end_of_data()
            raise urwid.ExitMainLoop()

    def update_readings(self):
        pending = 0
        for d in self.displays:
            if d.base_widget.update_readings(): pending += 1
        return pending

    def end_of_data(self):
        # pause for taking screenshot of simulated data
        if isinstance(time, SimulatedTime):
            while not self.loop.screen.get_input():
                pass


class GraphDisplay(urwid.WidgetWrap):
    def __init__(self,tap, smoothed):
        if smoothed:
            self.speed_graph = SpeedGraph(
                ['background','bar'],
                ['background','bar'],
                {(1,0):'bar:top'})

            self.cagraph = urwid.BarGraph(
                ['ca:background', 'ca:c', 'ca:a'],
                ['ca:background', 'ca:c', 'ca:a'],
                {(1,0):'ca:c:top', (2,0):'ca:a:top', })
        else:
            self.speed_graph = SpeedGraph([
                ('background', ' '), ('bar', ' ')],
                ['background', 'bar'])

            self.cagraph = urwid.BarGraph([
                ('ca:background', ' '),
                ('ca:c',' '),
                ('ca:a',' '),]
           )

        self.last_reading = urwid.Text("",align="right")
        scale = urwid.GraphVScale(graph_lines_captions(), graph_range())
        footer = self.last_reading
        graph_cols = urwid.Columns([('fixed', 5, scale),
            self.speed_graph, ('fixed', 4, self.cagraph)],
            dividechars = 1)
        self.top = urwid.Frame(graph_cols, footer=footer)

        self.spd = Speedometer(6)
        self.feed = tap.feed
        self.description = tap.description()
        super(GraphDisplay, self).__init__(self.top)

    def update_readings(self):
        f = self.feed()
        if f is None: raise EndOfData
        self.spd.update(f)
        s = self.spd.speed(1) # last sample
        c = curve(self.spd) # "curved" reading
        a = self.spd.speed() # running average
        self.speed_graph.append_log(s)

        self.last_reading.set_text([
            ('title', [self.description, "  "]),
            ('bar:num', [readable_speed(s), " "]),
            ('ca:c:num',[readable_speed(c), " "]),
            ('ca:a:num',readable_speed(a)) ])

        self.cagraph.set_data([
            [speed_scale(c),0],
            [0,speed_scale(a)],
            ], graph_range())



class GraphDisplayProgress(GraphDisplay):
    def __init__(self, tap, smoothed):
        GraphDisplay.__init__(self, tap, smoothed)

        self.spd = FileProgress(6, tap.expected_size)
        if smoothed:
            self.pb = urwid.ProgressBar('pr:n','pr:c',0,
                tap.expected_size, 'pr:cn')
        else:
            self.pb = urwid.ProgressBar('pr:n','pr:c',0,
                tap.expected_size)
        self.est = urwid.Text("")
        pbest = urwid.Columns([self.pb,('fixed',10,self.est)], 1)
        newfoot = urwid.Pile([self.top.footer, pbest])
        self.top.footer = newfoot

    def update_readings(self):
        GraphDisplay.update_readings(self)

        current, expected = self.spd.progress()
        self.pb.set_completion(current)
        e = self.spd.completion_estimate()
        if e is not None:
            self.est.set_text(readable_time(e,10))
        return current < expected

class SpeedGraph:
    def __init__(self, attlist, hatt=None, satt=None):
        if satt is None:
            self.graph = urwid.BarGraph(attlist, hatt)
        else:
            self.graph = urwid.BarGraph(attlist, hatt, satt)
        # override BarGraph's get_data
        self.graph.get_data = self.get_data

        self.smoothed = satt is not None

        self.log = []
        self.bar = []

    def get_data(self, max_col_row):
        maxcol, maxrow = max_col_row
        bar = self.bar[-maxcol:]
        if len(bar) < maxcol:
            bar = [[0]]*(maxcol-len(bar)) + bar
        return bar, graph_range(), graph_lines()

    def selectable(self):
        return False

    def render(self, max_col_row, focus=False):
        maxcol, maxrow = max_col_row
        left = max(0, len(self.log)-maxcol)
        pad = maxcol-(len(self.log)-left)

        topl = self.local_maximums(pad, left)
        yvals = [ max(self.bar[i]) for i in topl ]
        yvals = urwid.scale_bar_values(yvals, graph_range(), maxrow)

        graphtop = self.graph
        for i,y in zip(topl, yvals):
            s = self.log[ i ]
            txt = urwid.Text(readable_speed(s))
            label = urwid.AttrWrap(urwid.Filler(txt), 'reading')

            graphtop = urwid.Overlay(label, graphtop,
                ('fixed left', pad+i-4-left), 10,
                ('fixed top', max(0,y-2)), 1)

        return graphtop.render((maxcol, maxrow), focus)

    def local_maximums(self, pad, left):
        """
        Generate a list of indexes for the local maximums in self.log
        """
        ldist, rdist = 4,5
        l = self.log
        if len(l) <= ldist+rdist:
            return []

        dist = ldist+rdist
        highs = []

        for i in range(left+max(0, ldist-pad),len(l)-rdist+1):
            li = l[i]
            if li == 0: continue
            if i and l[i-1] is not None and l[i-1]>=li: continue
            if li is None or l[i+1]>li: continue
            highs.append((li, -i))

        highs.sort()
        highs.reverse()
        tag = [False]*len(l)
        out = []

        for li, i in highs:
            i=-i
            if tag[i]: continue
            for k in range(max(0,i-dist), min(len(l),i+dist)):
                tag[k]=True
            out.append(i)

        return out

    def append_log(self, s):
        x = speed_scale(s)
        o = [x]
        self.bar = self.bar[-300:] + [o]
        self.log = self.log[-300:] + [s]


def speed_scale(s):
    if s is None or s <= 0: return 0
    if logarithmic_scale:
        s = math.log(s, 2)
    s = min(graph_range(), max(0, s-graph_min()))
    return s


def delta_to_speed(delta):
    """delta_to_speed(delta) -> speed in bytes per second"""
    time_passed, byte_increase = delta
    if time_passed <= 0: return 0
    if int(time_passed*1000) == 0: return 0

    return int(byte_increase*1000)/int(time_passed*1000)



def readable_speed(speed):
    """
    readable_speed(speed) -> string
    speed is in bytes per second
    returns a readable version of the speed given
    """

    if speed == None or speed < 0: speed = 0

    units = "B/s  ", "KiB/s", "MiB/s", "GiB/s", "TiB/s"
    step = 1

    for u in units:

        if step > 1:
            s = "%4.2f " %(float(speed)/step)
            if len(s) <= 5: return s + u
            s = "%4.1f " %(float(speed)/step)
            if len(s) <= 5: return s + u

        if speed/step < 1024:
            return "%4d " %(speed/step) + u

        step = step * 1024

    return "%4d " % (speed/(step/1024)) + units[-1]


def readable_speed_bits(speed):
    """
    bits/s version of readable_speed()
    """
    if speed == None or speed < 0: speed = 0

    speed = speed * 8
    units = "b/s  ", "Kib/s", "Mib/s", "Gib/s", "Tib/s"
    step = 1

    for u in units:

        if step > 1:
            s = "%4.2f " %(float(speed)/step)
            if len(s) <= 5: return s + u
            s = "%4.1f " %(float(speed)/step)
            if len(s) <= 5: return s + u

        if speed/step < 1024:
            return "%4d " %(speed/step) + u

        step = step * 1024

    return "%4d " % (speed/(step/1024)) + units[-1]




def graphic_speed(speed):
    """graphic_speed(speed) -> string
    speed is bytes per second
    returns a graphic representing given speed"""

    if speed == None: speed = 0

    speed_val = [0]+[int(2**(x*5.0/3)) for x in range(20)]

    speed_gfx = [
        r"\                    ",
        r".\                   ",
        r"..\                  ",
        r"...\                 ",
        r"...:\                ",
        r"...::\               ",
        r"...:::\              ",
        r"...:::+|             ",
        r"...:::++|            ",
        r"...:::+++|           ",
        r"...:::+++#|          ",
        r"...:::+++##|         ",
        r"...:::+++###|        ",
        r"...:::+++###%|       ",
        r"...:::+++###%%/      ",
        r"...:::+++###%%%/     ",
        r"...:::+++###%%%//    ",
        r"...:::+++###%%%///   ",
        r"...:::+++###%%%////  ",
        r"...:::+++###%%%///// ",
        r"...:::+++###%%%//////",
        ]


    for i in range(len(speed_val)-1):
        low, high = speed_val[i], speed_val[i+1]
        if speed > high: continue
        if speed - low < high - speed:
            return speed_gfx[i]
        else:
            return speed_gfx[i+1]

    return speed_gfx[-1]



def file_size_feed(filename):
    """file_size_feed(filename) -> function that returns given file's size"""
    def sizefn(filename=filename,os=os):
        try:
            return os.stat(filename)[6]
        except:
            return 0
    return sizefn

class NetworkFeed:

    @classmethod
    def network_feed(cls, device, rxtx):
        """network_feed(device,rxtx) -> function that returns given device stream speed
        rxtx is "RX" or "TX"
        """
        assert rxtx in ["RX","TX"]

        r = re.compile(r"^\s*" + re.escape(device) + r":(.*)$", re.MULTILINE)

        def networkfn(devre=r,rxtx=rxtx):
            if device not in psutil.net_if_addrs().keys():
                sys.stderr.write("Network interface %s is not available\n\n" % device)
                sys.exit(1)

            if rxtx == 'RX':
                val=psutil.net_io_counters(pernic=True)[device].bytes_recv
            else:
                val=psutil.net_io_counters(pernic=True)[device].bytes_sent

            return int(val)

        return networkfn


class SubProcessFeed:

    def __init__(self, cmd=None):
        self.buffer_current_size = 1
        self.is_running = False
        self.cmd = cmd

    def stdinfn(self, *args, **kwargs):
        if self.is_running:
            return self.buffer_current_size
        else:
            self.is_running = True
            self.sub_process_job = SubprocessJob(feed=self)
            self.thread = threading.Thread(target=self.sub_process_job.run_job, args=(self.cmd ,))
            self.thread.start()
            return 0

    def file_size_feed(self):
        return self.stdinfn

    @classmethod
    def set_command(self, cmd):
        self.cmd = cmd

    def set_buffer_size(self, size):
        self.buffer_current_size = size

    def get_buffer_size(self):
        return self.buffer_current_size


class StdinFeed:

    def __init__(self):
        self.buffer_current_size = 0
        self.is_running = False

    def stdinfn(self, *args, **kwargs):
        if self.is_running:
            return self.buffer_current_size
        else:
            self.is_running = True
            self.stdin_job = StdinJob(feed=self)
            self.thread = threading.Thread(target=self.stdin_job.run_job)
            self.thread.start()
            return 0

    def file_size_feed(self):
        return self.stdinfn

    def set_buffer_size(self, size):
        self.buffer_current_size = size

    def get_buffer_size(self):
        return self.buffer_current_size


class SubprocessJobQueue:
    job_list = []

    @classmethod
    def add_job(cls, id):
        cls.job_list.append(id)

    @classmethod
    def stop_all_job(cls):
        for item in cls.job_list:
            item.stop_job()

class SubprocessJob:

    def __init__(self, feed):
        self.current_job_process = None
        self.current_job_process_is_stop = None
        self.default_read_size = 10240*100
        self.feed = feed
        SubprocessJobQueue.add_job(self)

    def stop_job(self):
        if self.current_job_process:
            try:
                self.current_job_process.terminate()
            except:
                pass
            self.current_job_process_is_stop = True
            time.sleep(0.2)
            return True

        return False

    def run_job(self, args):

        self.current_job_process = subprocess.Popen(args, shell=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, bufsize=self.default_read_size)


        size = 0

        def is_avail():
            return self.current_job_process.stdout.peek()

        while True:
            if self.current_job_process and is_avail() and not self.current_job_process_is_stop:
                self.current_job_process.stdout.read(self.default_read_size)
                size+= self.default_read_size
                self.feed.set_buffer_size(size)
            else:
                self.stop_job()
                time.sleep(0.2)
                self.feed.set_buffer_size(None)
                break


class StdinJobQueue:
    job_list = []

    @classmethod
    def add_job(cls, id):
        cls.job_list.append(id)

    @classmethod
    def stop_all_job(cls):
        for item in cls.job_list:
            item.stop_job()

class StdinJob:

    def __init__(self, feed):
        self.current_job_process = None
        self.current_job_process_is_stop = None
        self.default_read_size = 10240*100
        self.feed = feed
        StdinJobQueue.add_job(self)

    def stop_job(self):
        self.current_job_process_is_stop = True
        time.sleep(0.3)
        return True

    def run_job(self):
        size = 0
        stdin_handler = sys.stdin.buffer.read

        while not self.current_job_process_is_stop:
            i, _, _ = select.select( [sys.stdin], [], [])

            if not i:
                time.sleep(0.03)
                continue

            try:
                data = stdin_handler(self.default_read_size)
            except:
                data = None

            if data:
                size+=self.default_read_size
                self.feed.set_buffer_size(size)

            else:
                self.stop_job()
                time.sleep(0.2)
                self.feed.set_buffer_size(None)
                break


class SimulatedFeed:

    @classmethod
    def simulated_feed(cls, data):
        total = 0
        adjusted_data = [0]
        for d in data:
            d = int(d)
            adjusted_data.append(d + total)
            total += d

        def simfn(data=adjusted_data):
            if data:
                return int(data.pop(0))
            return None
        return simfn

class SimulatedTime:
    def __init__(self, start):
        self.t = start
    def sleep(self, length):
        self.t += length
    def time(self):
        return self.t


class FileProgress:
    """FileProgress monitors a file's size vs time and expected size to
    produce progress and estimated completion time readings"""

    samples_for_estimate = 4

    def __init__(self, maxlog, expected_size):
        """FileProgress(expected_size)
        expected_size is the file's expected size in bytes"""

        self.expected_size = expected_size
        self.speedometer = Speedometer(maxlog)
        self.current_size = None
        self.speed = self.speedometer.speed
        self.delta = self.speedometer.delta

    def update(self, current_size):
        """update(current_size)
        current_size is the current file size
        update will record the current size and time"""

        self.current_size = current_size
        self.speedometer.update(self.current_size)

    def progress(self):
        """progress() -> (current size, expected size)
        current size will be None until update is called"""

        return self.current_size, self.expected_size

    def completion_estimate(self):
        """completion_estimate() -> estimated seconds remaining
        will return None if not enough data is available"""

        d = self.speedometer.delta(self.samples_for_estimate)
        if not d: return None  # not enough readings
        (seconds,bytes) = d
        if bytes <= 0: return None  # currently stalled
        remaining = self.expected_size - self.current_size
        if remaining <= 0: return 0  # all done -- no time remaining

        seconds_left = float(remaining)*seconds/bytes

        return seconds_left

    def average_speed(self):
        """average_speed() -> bytes per second since start
        will return None if not enough data"""
        return self.speedometer.speed()

    def current_speed(self):
        """current_speed() -> latest bytes per second reading
        will return None if not enough data"""
        return self.speedometer.speed(1)



def graphic_progress(progress, columns):
    """graphic_progress(progress, columns) -> string
    progress is a tuple of (value, max)
    columns is length of string returned
    returns a graphic representation of value vs. max"""
    value, max = progress

    f = float(value) / float(max)
    if f > 1: f = 1
    if f < 0: f = 0

    filled = int(f*columns)
    gfx = "#" * filled + "-" * (columns-filled)

    return gfx


def time_as_units(seconds):
    """time_units(seconds) -> list of (count, suffix) tuples
    returns a unit breakdown for the given number of seconds"""

    if seconds==None: seconds=0

    # (multiplicative factor, suffix)
    units = (1,"s"), (60,"m"), (60,"h"), (24,"d"), (7,"w"), (52,"y")

    scale = 1
    topunit = -1
    # find the top unit to use
    for mul, suf in units:
        if seconds / (scale*mul) < 1: break
        topunit = topunit+1
        scale = scale * mul

    # build the list reading backwards from top unit
    out = []
    for i in range(topunit, -1, -1):
        mul,suf = units[i]
        value = int(seconds/scale)
        seconds = seconds - value * scale
        scale = scale / mul
        out.append((value, suf))

    return out


def readable_time(seconds, columns=None):
    """readable_time(seconds, columns=None) -> string
    return the seconds as a readable string
    if specified, columns is the maximum length of the returned string"""

    out = ""
    for value, suf in time_as_units(seconds):
        new_out = out
        if out: new_out = new_out + ' '
        new_out = new_out + value + suf
        if columns and len(new_out) > columns: break
        out = new_out

    return out


class ArgumentError(Exception):
    pass


def console():
    """Console mode"""
    try:
        cols, urwid_ui, zero_files, exit_on_complete, num_colors, shiny_colors = parse_args()
    except ArgumentError:
        sys.stderr.write(__usage__)
        if not URWID_IMPORTED:
            sys.stderr.write(__urwid_info__)
        sys.stderr.write("""\nPython Version: %d.%d\n""""""Urwid >= 0.9.9.1 detected: %s\nUTF-8 encoding detected: %s\n
""" % (sys.version_info[:2] + (["NO","yes"][URWID_IMPORTED],) +
        (["NO","yes"][URWID_UTF8],)))
        return

    update_scale()

    if zero_files:
        for c in cols:
            a = []
            for tap in c:
                if hasattr(tap, 'report_zero'):
                    tap.report_zero()

    try:
        # wait for every tap to be able to read
        wait_all(cols)
    except KeyboardInterrupt:
        return

    # plain-text mode
    if not urwid_ui:
        [[tap]] = cols

        if tap.ftype == 'file_exp':
            do_progress(tap.feed, tap.expected_size, exit_on_complete)
        else:
            do_simple(tap.feed)
        return

    do_display(cols, urwid_ui, exit_on_complete, num_colors, shiny_colors)


def do_display(cols, urwid_ui, exit_on_complete, num_colors, shiny_colors):
    mg = MultiGraphDisplay(cols, urwid_ui, exit_on_complete, shiny_colors)
    mg.main(num_colors)


class SubProcessTap:
    def __init__(self, cmd=None):
        self.ftype = 'subprocess'
        self.feed = SubProcessFeed(cmd=cmd).file_size_feed()
        self.wait = False

    def report_zero(self):
        self.wait = False

    def description(self):
        return "Sub process"

    def wait_creation(self):
        return


class FileTap:
    def __init__(self, name):
        self.ftype = 'file'
        self.file_name = name
        self.feed = file_size_feed(name)
        self.wait = True

    def set_expected_size(self, size):
        self.expected_size = int(size)
        self.ftype = 'file_exp'

    def report_zero(self):
        self.wait = False

    def description(self):
        return "FILE: "+ self.file_name

    def wait_creation(self):
        if not self.wait:
            return

        if not os.path.exists(self.file_name):
            sys.stdout.write("Waiting for '%s' to be created...\n"
                % self.file_name)
            while not os.path.exists(self.file_name):
                time.sleep(1)


class StdinTap:
    def __init__(self):
        self.ftype = 'stdin'
        self.feed = StdinFeed().file_size_feed()
        self.wait = False

    def report_zero(self):
        self.wait = False

    def description(self):
        return "Pipe/Stdin"

    def wait_creation(self):
        return False


class NetworkTap:
    def __init__(self, rxtx, interface):
        self.ftype = rxtx
        self.interface = interface
        self.feed = NetworkFeed.network_feed(interface, rxtx)

    def description(self):
        return self.ftype+": "+self.interface

    def wait_creation(self):
        if self.feed() is not None:
            return
        sys.stdout.write("Waiting for network statistics from interface '%s'...\n" % self.interface)
        while self.feed() == None:
            time.sleep(1)


def parse_args():
    args = sys.argv[1:]
    tap = None

    zero_files = False
    interval_set = False
    exit_on_complete = False
    num_colors = 16
    colors_set = False
    shiny_colors = None
    cols = []
    taps = []
    isatty = False

    def push_tap(tap, taps):
        if tap is None: return
        taps.append(tap)

    if not sys.stdin.isatty():
        isatty = True
        push_tap(tap, taps)
        tap = StdinTap()
        urwid_ui = False

    elif URWID_UTF8:
        urwid_ui = 'smoothed'

    elif URWID_IMPORTED:
        urwid_ui = 'blocky'

    else:
        urwid_ui = False

    i = 0
    while i < len(args):
        op = args[i]
        if op in ("-h","--help"):
            raise ArgumentError

        elif op in ("-d", "-i", "-r", "-rx", "-t", "-tx", "-f", "-k", "-m", "-n"):
            # combine two part arguments with the following argument
            try:
                if op != "-f": # keep support for -f being optional
                    args[i+1] = op + args[i+1]
            except IndexError:
                raise ArgumentError
            push_tap(tap, taps)
            tap = None

        elif op == "-S":
            # undocumented simulation option
            simargs = []
            i += 1
            while i < len(args) and args[i][:1] != "-":
                simargs.append(args[i])
                i += 1
            simulate = tap
            if not simulate:
                simulate = taps[-1]
            simulate.feed = SimulatedFeed.simulated_feed(simargs)
            global time
            time = SimulatedTime(time.time())
            continue

        elif op[:2] == '-d':
            push_tap(tap, taps)
            process_tap = SubProcessTap(cmd=op[2:])
            tap = SubProcessTap(cmd=op[2:])

        elif op == "-p":
            # disable urwid ui
            urwid_ui = False

        elif not sys.stdin.isatty():
            urwid_ui = False

        elif op == "-b":
            urwid_ui = 'blocky'

        elif op == "-s":
            global readable_speed
            global units_per_second
            readable_speed = readable_speed_bits
            units_per_second = 'bits'

        elif op == "-x":
            exit_on_complete = True

        elif op == "-z":
            zero_files = True

        elif op[:2] == "-k":
            if colors_set: raise ArgumentError
            try:
                num_colors = int(op[2:])
                assert num_colors in VALID_NUM_COLORS
            except:
                raise ArgumentError
            if num_colors>16:
                shiny_colors = num_colors
            colors_set = True

        elif op[:2] == "-i":
            if interval_set: raise ArgumentError

            global INTERVAL_DELAY
            global INITIAL_DELAY
            try:
                INTERVAL_DELAY = float(op[2:])
            except:
                raise ArgumentError

            if INTERVAL_DELAY<INITIAL_DELAY:
                INITIAL_DELAY=INTERVAL_DELAY
            interval_set = True

        elif op == "-l":
            global logarithmic_scale
            logarithmic_scale = False

        elif op.startswith("-m"):
            global chart_maximum
            try:
                chart_maximum = int(op[2:])
            except:
                raise ArgumentError

        elif op.startswith("-n"):
            global chart_minimum
            try:
                chart_minimum = int(op[2:])
            except:
                raise ArgumentError

        elif op.startswith("-rx"):
            push_tap(tap, taps)
            tap = NetworkTap("RX", op[3:])

        elif op.startswith("-r"):
            push_tap(tap, taps)
            tap = NetworkTap("RX", op[2:])

        elif op.startswith("-tx"):
            push_tap(tap, taps)
            tap = NetworkTap("TX", op[3:])

        elif op.startswith("-t"):
            push_tap(tap, taps)
            tap = NetworkTap("TX", op[2:])

        elif op == "-c":
            push_tap(tap, taps)
            if not taps:
                raise ArgumentError
            cols.append(taps)
            taps = []
            tap = None

        elif tap == None:
            tap = FileTap(op)

        elif tap and tap.ftype == 'file':
            try:
                tap.set_expected_size(op)
                push_tap(tap, taps)
                tap = None
            except:
                raise ArgumentError
        else:
            raise ArgumentError

        i += 1

    if urwid_ui and not URWID_IMPORTED:
        raise ArgumentError

    push_tap(tap, taps)

    if not taps:
        autodetect_taps(taps)

    if not urwid_ui and (len(taps)>1 or cols):
        raise ArgumentError

    if not taps:
        raise ArgumentError
    cols.append(taps)

    if chart_maximum <= chart_minimum:
        raise ArgumentError

    return cols, urwid_ui, zero_files, exit_on_complete, num_colors, shiny_colors

def autodetect_taps(taps):
    print("no taps specified, add all... ")
    for dev in psutil.net_if_addrs().keys():
        taps.append(NetworkTap('RX', dev))
        taps.append(NetworkTap('TX', dev))

def do_simple(feed):
    try:
        spd = Speedometer(6)
        f = feed()

        if f is None:
            return

        spd.update(f)
        time.sleep(INITIAL_DELAY)

        while 1:
            f = feed()
            if f is None: return
            spd.update(f)
            s = spd.speed(1) # last sample
            c = curve(spd) # "curved" reading
            a = spd.speed() # running average
            show(s,c,a)
            time.sleep(INTERVAL_DELAY)

    except KeyboardInterrupt:
        SubprocessJobQueue.stop_all_job()
        StdinJobQueue.stop_all_job()

def curve(spd):
    """Try to smooth speed fluctuations"""
    val = [6, 5, 4, 3, 2, 1] # speed sampling relative weights
    wtot = 0 # total weighting
    ws = 0.0 # weighted speed
    for i in range(len(val)):
        d = spd.delta(1,i)
        if d==None:
            break # ran out of data
        t, b = d
        v = val[i]
        wtot += v
        ws += float(b)*v/t
    return delta_to_speed((wtot, ws))


def show(s, c, a, out = sys.stdout.write):
    out(readable_speed(s))
    out("  c:" + readable_speed(c))
    out("  A:" + readable_speed(a))
    out("  (" + graphic_speed(s)+")")
    out('\n')
    sys.stdout.flush()


def do_progress(feed, size, exit_on_complete):
    try:
        fp = FileProgress(4, int(size))
        out = sys.stdout.write

        f = feed()
        if f is None: return
        fp.update(f)
        time.sleep(INITIAL_DELAY)
        while 1:
            f = feed()
            if f is None: return
            fp.update(f)
            out('('+graphic_speed(fp.current_speed())+')')
            out(readable_speed(fp.current_speed()))
            out(' ['+graphic_progress(fp.progress(), 36)+']')
            out('  '+readable_time(fp.completion_estimate()))
            out('\n')
            current, expected = fp.progress()
            if exit_on_complete and current >= expected: break
            time.sleep(INTERVAL_DELAY)

    except KeyboardInterrupt:
        SubprocessJob.stop_job()
        StdinJob.stop_job()


def wait_all(cols):
    for c in cols:
        for tap in c:
            tap.wait_creation()

def shiny(y):
    """
    return a value between 0 (dark) and 1 (bright) for a given y position
    between 0 (top) and 1 (bottom) to create a "shiny" background effect
    """
    gamma = 1 - (4 * (y - 0.25)) ** 2 if y < 0.5 else (2*y - 1) ** 2
    return max(0, min(1, (gamma - 0.2)*1.2))

class ShinyMap(urwid.WidgetPlaceholder):
    def __init__(self, w, colors):
        assert colors in (88, 256)
        self._colors = colors
        super(ShinyMap, self).__init__(w)
        self._shiny_cache = []
        self._shiny_cache_maxrow = None

    def _rebuild_shiny_cache(self, maxrow):
        prev_gray = None
        if self._shiny_cache_maxrow == maxrow:
            return
        self._shiny_cache = []
        self._shiny_cache_maxrow = maxrow
        for y in range(maxrow):
            gamma = shiny(1 - (y+0.5)/maxrow)
            if self._colors == 256:
                gamma = gamma * 25 + 10
            else:
                gamma = gamma * 45
            spec = urwid.AttrSpec('g70', 'g%d' % gamma, self._colors)
            gray = spec.background
            if prev_gray == gray:
                amap, num = self._shiny_cache[-1]
                self._shiny_cache[-1] = amap, num + 1
                continue
            prev_gray = gray
            amap = {
                'background': spec,
                'bar:top': urwid.AttrSpec('#488', gray, self._colors),
                'reading': spec,
                'ca:background': spec,
                'ca:c:top': urwid.AttrSpec('#66d', gray, self._colors),
                'ca:a:top': urwid.AttrSpec('#6b6', gray, self._colors),
                }
            self._shiny_cache.append((amap, 1))

    def render(self, size, focus=False):
        maxcol, maxrow = size
        canv = super(ShinyMap, self).render(size, focus)
        self._rebuild_shiny_cache(maxrow)
        slivers = []
        y = 0
        for amap, run in self._shiny_cache:
            c = urwid.CompositeCanvas(canv)
            c.trim(y, run)
            y = y + run
            c.fill_attr_apply(amap)
            slivers.append((c, None, False))
        return urwid.CanvasCombine(slivers)



if __name__ == "__main__":
    try:
        console()
    except KeyboardInterrupt as err:
        pass
