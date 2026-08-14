from decimal import Decimal
from scripts.models import Cedolino, ZERO
from scripts.parsers.zucchetti2 import _parse_totali, _build_lines


def test_zucchetti2_parse_totali_arrotondamento_presente():
    ''' testa la funzione di parse dei totali con valore arrotondamento presente '''

    ced = Cedolino(file_path='test_path', formato="zucchetti2")
    words = [
        {'text': 'Perm.P.A.R', 'x0': 30.29, 'x1': 70.792, 'top': 726.35, 'doctop': 1568.35, 'bottom': 733.35, 'upright': True, 'height': 7.0, 'width': 40.502, 'direction': 'ltr'},
        {'text': '8,66666', 'x0': 122.29, 'x1': 151.221, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999997, 'direction': 'ltr'},
        {'text': '2,33334', 'x0': 188.0, 'x1': 216.93099999999998, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999983, 'direction': 'ltr'},
        {'text': '6,33332', 'x0': 252.0, 'x1': 280.931, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999983, 'direction': 'ltr'},
        {'text': 'ORE', 'x0': 373.71, 'x1': 389.81, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 16.100000000000023, 'direction': 'ltr'},
        {'text': 'ARROTONDAMENTO', 'x0': 424.554, 'x1': 476.87399999999997, 'top': 723.968, 'doctop': 1565.9679999999998, 'bottom': 729.968, 'upright': True, 'height': 6.0, 'width': 52.31999999999999, 'direction': 'ltr'},
        {'text': '0,31', 'x0': 562.33, 'x1': 577.9050000000001, 'top': 725.08, 'doctop': 1567.08, 'bottom': 732.08, 'upright': True, 'height': 7.0, 'width': 15.575000000000045, 'direction': 'ltr'},
    ]
    lines = _build_lines(words)
    _parse_totali(ced, lines, "")

    assert ced.totali.arrotondamento == Decimal("0.31")

def test_zucchetti2_parse_totali_arrotondamento_assente():
    ''' testa la funzione di parse dei totali con valore arrotondamento mancante '''

    ced = Cedolino(file_path='test_path', formato="zucchetti2")
    words = [
        {'text': 'Perm.P.A.R', 'x0': 30.29, 'x1': 70.792, 'top': 726.35, 'doctop': 1568.35, 'bottom': 733.35, 'upright': True, 'height': 7.0, 'width': 40.502, 'direction': 'ltr'},
        {'text': '8,66666', 'x0': 122.29, 'x1': 151.221, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999997, 'direction': 'ltr'},
        {'text': '2,33334', 'x0': 188.0, 'x1': 216.93099999999998, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999983, 'direction': 'ltr'},
        {'text': '6,33332', 'x0': 252.0, 'x1': 280.931, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 28.930999999999983, 'direction': 'ltr'},
        {'text': 'ORE', 'x0': 373.71, 'x1': 389.81, 'top': 725.78, 'doctop': 1567.78, 'bottom': 732.78, 'upright': True, 'height': 7.0, 'width': 16.100000000000023, 'direction': 'ltr'},
        {'text': 'ARROTONDAMENTO', 'x0': 424.554, 'x1': 476.87399999999997, 'top': 723.968, 'doctop': 1565.9679999999998, 'bottom': 729.968, 'upright': True, 'height': 6.0, 'width': 52.31999999999999, 'direction': 'ltr'},
        # il valore arrotondamento e' mancante volutamente, come succede in alcuni cedolini
        # {'text': '0,31', 'x0': 562.33, 'x1': 577.9050000000001, 'top': 725.08, 'doctop': 1567.08, 'bottom': 732.08, 'upright': True, 'height': 7.0, 'width': 15.575000000000045, 'direction': 'ltr'},
    ]
    lines = _build_lines(words)
    _parse_totali(ced, lines, "")

    assert ced.totali.arrotondamento == ZERO