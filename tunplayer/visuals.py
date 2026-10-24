"""Original vector artwork and a consistent local icon set for the GTK interface."""
import hashlib
from functools import lru_cache
import math
import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf

ICONS = {
    'radio': '<rect x="3" y="8" width="18" height="13" rx="3"/><path d="M5 8 19 3M6 12h5m-5 4h5"/><circle cx="16" cy="15" r="2"/>',
    'home': '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    'live': '<rect x="3" y="6" width="18" height="14" rx="3"/><path d="m8 2 4 4 4-4"/><path d="m10 10 5 3-5 3z"/>',
    'movie': '<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M3 10h18M7 4l4 6m3-6 4 6"/>',
    'guide': '<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M8 2v4m8-4v4M3 10h18m-13 5h3m3 0h2"/>',
    'heart': '<path d="M20.8 4.6a5.4 5.4 0 0 0-7.6 0L12 5.8l-1.2-1.2a5.4 5.4 0 0 0-7.6 7.6L12 21l8.8-8.8a5.4 5.4 0 0 0 0-7.6z"/>',
    'history': '<path d="M3 11a9 9 0 1 1 2.5 7M3 4v7h7m2-4v6l4 2"/>',
    'sources': '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M12 6.5h5m-5 11h5"/>',
    'settings': '<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2 2m8.8 8.8 2 2m0-12.8-2 2m-8.8 8.8-2 2"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'play': '<path d="m8 4 12 8-12 8z"/>',
    'previous': '<path d="M5 5v14m14-14L8 12l11 7z"/>',
    'next': '<path d="M19 5v14M5 5l11 7-11 7z"/>',
    'close': '<path d="m6 6 12 12M6 18 18 6"/>',
    'pause': '<path d="M8 5v14M16 5v14"/>',
    'stop': '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    'arrow': '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    'back': '<path d="M19 12H5m6-6-6 6 6 6"/>',
    'refresh': '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/>',
    'fullscreen': '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    'fullscreen-exit': '<path d="M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5"/>',
    'subtitles': '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M6 11h5m3 0h4M6 15h3m3 0h6"/>',
    'audio': '<path d="M5 9H2v6h3l5 5V4zM14 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
    'shield': '<path d="m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5z"/><path d="m8 12 3 3 5-6"/>',
    'spark': '<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z"/>',
    'edit': '<path d="m14 5 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z"/>',
    'trash': '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    'folder': '<path d="M3 20V5a2 2 0 0 1 2-2h5l3 4h6a2 2 0 0 1 2 2v11z"/>',
    'rewind': '<path d="m8 4-5 5 5 5M3 9h9a8 8 0 0 1 8 8v3"/>',
    'forward': '<path d="m16 4 5 5-5 5m5-5h-9a8 8 0 0 0-8 8v3"/>',
    'record': '<circle cx="12" cy="12" r="6"/>',
}


@lru_cache(maxsize=192)
def icon_pixbuf(name, size=18, color='#a8b0bf'):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" '
           f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')
    loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
    loader.write(svg.encode()); loader.close()
    return loader.get_pixbuf()


def icon(name, size=18, color='#a8b0bf'):
    image = Gtk.Image.new_from_pixbuf(icon_pixbuf(name,size,color))
    image.set_valign(Gtk.Align.CENTER)
    return image


def rounded(cr, x, y, width, height, radius):
    radius=min(radius,width/2,height/2)
    cr.new_sub_path()
    for cx,cy,start in [(x+width-radius,y+radius,-math.pi/2),(x+width-radius,y+height-radius,0),
                        (x+radius,y+height-radius,math.pi/2),(x+radius,y+radius,math.pi)]:
        cr.arc(cx,cy,radius,start,start+math.pi/2)
    cr.close_path()


def draw_hero(cr, width, height):
    """Cinematic desert panorama; also renderable to a standalone Cairo surface."""
    cr.save(); rounded(cr,0,0,width,height,22); cr.clip()
    cr.scale(width/1100,height/350)
    gradient=cairo.LinearGradient(0,0,1100,350)
    gradient.add_color_stop_rgb(0,.075,.105,.11)
    gradient.add_color_stop_rgb(.5,.10,.17,.17)
    gradient.add_color_stop_rgb(1,.24,.28,.24)
    cr.set_source(gradient); cr.paint()
    glow=cairo.RadialGradient(840,102,5,840,102,210)
    glow.add_color_stop_rgba(0,.98,.73,.40,.35);glow.add_color_stop_rgba(1,.98,.73,.40,0)
    cr.set_source(glow);cr.paint()
    sun=cairo.LinearGradient(0,40,0,180)
    sun.add_color_stop_rgb(0,.98,.87,.60);sun.add_color_stop_rgb(1,.88,.61,.34)
    cr.set_source(sun);cr.arc(854,119,65,0,math.tau);cr.fill()
    # Fine orbital line and stars give depth without any external bitmap.
    cr.set_source_rgba(.95,.91,.74,.15);cr.set_line_width(.8)
    cr.save();cr.translate(850,130);cr.scale(1,.55);cr.rotate(-.2);cr.arc(0,0,185,0,math.tau);cr.stroke();cr.restore()
    for x,y,r in [(590,45,1.2),(730,58,1),(995,62,1.3),(1040,142,1),(660,111,.7)]:
        cr.set_source_rgba(.96,.90,.72,.55);cr.arc(x,y,r,0,math.tau);cr.fill()
    # Successive dunes: warm distant ridge, cool middle ridge, shadowed foreground.
    cr.move_to(450,350);cr.curve_to(600,300,628,169,777,205)
    cr.curve_to(925,245,955,171,1100,143);cr.line_to(1100,350);cr.close_path()
    dunes=cairo.LinearGradient(0,170,0,350);dunes.add_color_stop_rgb(0,.57,.43,.30);dunes.add_color_stop_rgb(1,.23,.26,.23)
    cr.set_source(dunes);cr.fill()
    cr.move_to(400,350);cr.curve_to(650,337,668,218,815,251);cr.curve_to(952,285,995,224,1100,238)
    cr.line_to(1100,350);cr.close_path();cr.set_source_rgb(.12,.24,.24);cr.fill()
    cr.move_to(400,350);cr.curve_to(650,260,760,347,890,307);cr.curve_to(980,280,1020,279,1100,312)
    cr.line_to(1100,350);cr.close_path();cr.set_source_rgb(.075,.15,.16);cr.fill()
    cr.set_line_width(.65)
    for i in range(9):
        cr.move_to(690+i*7,350);cr.curve_to(830+i*7,290+i*5,970,315+i*3,1100,326+i*3)
        cr.set_source_rgba(.64,.76,.65,.07);cr.stroke()
    shade=cairo.LinearGradient(0,0,1100,0)
    shade.add_color_stop_rgba(0,.055,.075,.085,1)
    shade.add_color_stop_rgba(.40,.055,.075,.085,.94)
    shade.add_color_stop_rgba(.64,.055,.075,.085,.25)
    shade.add_color_stop_rgba(1,.055,.075,.085,0)
    cr.set_source(shade);cr.paint();cr.restore()


PALETTES = [('#153d40','#255b59','#b2e5cd'),('#322c55','#52446e','#dac4f8'),
            ('#493829','#76543b','#f4d4a6'),('#18334b','#285572','#b9dcf1'),
            ('#3f2937','#664355','#edc1ce'),('#2d3b29','#4b6141','#c9e4ac')]


def rgb(value):
    return tuple(int(value[i:i+2],16)/255 for i in (1,3,5))


def draw_cover(cr, width, height, name, group='', movie=False):
    digest=hashlib.sha256((name+group).encode()).digest()
    base,light,ink=PALETTES[digest[0]%len(PALETTES)]
    cr.save();rounded(cr,0,0,width,height,14);cr.clip()
    gradient=cairo.LinearGradient(0,height,width,0)
    gradient.add_color_stop_rgb(0,*rgb(base));gradient.add_color_stop_rgb(1,*rgb(light))
    cr.set_source(gradient);cr.paint()
    cr.set_line_width(1)
    for i in range(5):
        cr.set_source_rgba(*rgb(ink),.08)
        if digest[1]%2:
            cr.arc(width*.80,height*.48,30+i*24,0,math.tau)
        else:
            rounded(cr,width*.63-i*19,-35+i*8,140+i*32,140+i*28,40)
        cr.stroke()
    cr.set_source_rgba(*rgb(ink),.10);cr.arc(width*.82,height*.92,85,0,math.tau);cr.fill()
    initials=''.join(part[0] for part in name.split()[:2]).upper() or 'TV'
    cr.select_font_face('DejaVu Sans',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(40 if movie else 34)
    ext=cr.text_extents(initials)
    x=(width-ext.width)/2-ext.x_bearing;y=(height-ext.height)/2-ext.y_bearing+8
    cr.set_source_rgb(*rgb(ink));cr.move_to(x,y);cr.show_text(initials)
    cr.set_source_rgba(*rgb(ink),.40);cr.set_line_width(1.2)
    cr.move_to(width/2-13,height*.80);cr.line_to(width/2+13,height*.80);cr.stroke()
    cr.restore()


class HeroArt(Gtk.DrawingArea):
    def __init__(self):
        super().__init__();self.set_size_request(-1,380)
        self.connect('draw',lambda w,cr:draw_hero(cr,w.get_allocated_width(),w.get_allocated_height()) or False)


class ChannelArt(Gtk.DrawingArea):
    def __init__(self, name, group, movie=False):
        super().__init__();self.set_size_request(-1,156 if movie else 132)
        self.connect('draw',lambda w,cr:draw_cover(cr,w.get_allocated_width(),w.get_allocated_height(),name,group,movie) or False)


class MediaArt(Gtk.DrawingArea):
    """Logo containment for live TV, edge-to-edge poster cropping for VOD."""
    def __init__(self,name,group,mode='logo',compact=False):
        super().__init__();self.name=name;self.group=group;self.mode=mode;self.pixbuf=None
        self.set_size_request(-1,100 if compact and mode=='logo' else 126 if mode=='logo' else 216 if compact else 276)
        self.connect('draw',self.paint)

    def set_pixbuf(self,pixbuf):
        self.pixbuf=pixbuf;self.queue_draw()

    def paint(self,widget,cr):
        from gi.repository import Gdk
        width,height=self.get_allocated_width(),self.get_allocated_height()
        draw_cover(cr,width,height,self.name,self.group,self.mode!='logo')
        if self.pixbuf:
            cr.save();rounded(cr,0,0,width,height,12);cr.clip()
            if self.mode=='logo':
                cr.set_source_rgb(.085,.11,.145);cr.paint()
                scale=min(width*.72/self.pixbuf.get_width(),height*.60/self.pixbuf.get_height())
            else:scale=max(width/self.pixbuf.get_width(),height/self.pixbuf.get_height())
            x=(width-self.pixbuf.get_width()*scale)/2;y=(height-self.pixbuf.get_height()*scale)/2
            cr.translate(x,y);cr.scale(scale,scale)
            Gdk.cairo_set_source_pixbuf(cr,self.pixbuf,0,0);cr.paint();cr.restore()
        if self.mode!='logo':
            cr.save();rounded(cr,0,0,width,height,12);cr.clip()
            shade=cairo.LinearGradient(0,0,0,height)
            shade.add_color_stop_rgba(0,0,0,0,.38);shade.add_color_stop_rgba(.3,0,0,0,0)
            shade.add_color_stop_rgba(1,0,0,0,.30);cr.set_source(shade);cr.paint();cr.restore()
        return False

ICONS.update({
    'series':'<rect x="3" y="8" width="18" height="13" rx="2"/><path d="M6 4h12M9 1h6m-4 11 5 3-5 3z"/>',
    'grid':'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    'list':'<path d="M8 5h13M8 12h13M8 19h13M3 5h.01M3 12h.01M3 19h.01"/>',
    'filter':'<path d="M3 5h18M6 12h12M9 19h6"/>',
})

ICONS['info']='<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>'
