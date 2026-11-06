"""Bounded overlapping PDF tiles with provenance, never silent downsampling."""
import math


def plan(width_pt,height_pt,dpi=200,tile_px=1800,overlap_px=120,max_tiles=64):
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0
               for x in (width_pt,height_pt,dpi,tile_px)):
        raise ValueError('positive finite page dimensions, DPI and tile size required')
    if not 0 <= overlap_px < tile_px or dpi > 600:
        raise ValueError('invalid overlap or DPI above bounded renderer limit')
    width,height=math.ceil(width_pt*dpi/72),math.ceil(height_pt*dpi/72)
    step=tile_px-overlap_px
    xs=list(range(0,max(1,width-overlap_px),step))
    ys=list(range(0,max(1,height-overlap_px),step))
    if len(xs)*len(ys)>max_tiles:
        raise ValueError('tile budget exceeded; choose explicit regions, do not silently omit detail')
    return [dict(x=x,y=y,width=min(tile_px,width-x),height=min(tile_px,height-y),dpi=dpi,
                 bbox_pt=[x*72/dpi,y*72/dpi,min(width,x+tile_px)*72/dpi,min(height,y+tile_px)*72/dpi])
            for y in ys for x in xs]
