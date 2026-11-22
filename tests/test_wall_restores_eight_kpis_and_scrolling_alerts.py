"""Requested wall presentation: the full metric strip and scrolling footer."""
from pathlib import Path
import re

PAGE = (Path(__file__).parents[1]/'sdi-intelligence-backend'/'sdi-estimating-wall.html').read_text(encoding='utf-8')


def function(name):
    return re.search(r'^function '+name+r'\([^\n]*\)\{.*?^\}',PAGE,re.M|re.S).group()


def test_all_eight_original_metrics_are_the_visible_primary_row():
    code = function('renderKpis')
    labels = re.findall(r'\["([^"]+)",',code)
    assert labels == ['Runs today','Completed · 24 h','Success · 7 days','Median run · 7 days',
                      '90th pct · 7 days','Queue','Capacity','ETA error']
    assert '$("kpis").innerHTML = tiles.map(tile).join("")' in code
    assert 'headline.map' not in code and 'wallTelemetry' not in code
    assert '#kpis.kpis{grid-template-columns:repeat(8,minmax(0,1fr))' in PAGE


def test_the_scroll_is_not_disabled_when_operational_alerts_are_empty():
    code = function('renderTicker')
    assert 'run still' not in code
    assert 'ticker-copy' in code and 'aria-hidden' in code
    assert 'attentionRows' in code
    assert 'No operational alerts reported. Estimate review status is shown separately.' in PAGE
    assert 'textContent = message' in code  # Never interpolate alert text as HTML.


def test_ticker_refresh_preserves_its_animation_and_can_be_paused():
    code = function('renderTicker')
    assert 't.dataset.message !== message' in code
    assert '.ticker:hover .run,.ticker:focus-within .run{animation-play-state:paused}' in PAGE
    assert '.ticker .run{animation:none!important' in PAGE
    assert '@media(prefers-reduced-motion:reduce)' in PAGE


def test_brand_and_separate_health_and_review_banners_remain():
    assert 'aria-label="we.are.sdi"' in PAGE
    assert 'id="reviewBanner"' in PAGE and 'id="bannerText"' in PAGE
    assert 'not the full batch backlog' in PAGE
    assert 'batch rows not yet submitted are not counted' in PAGE
