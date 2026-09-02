"""Extrae la topologia del dashboard desde el HTML servido en produccion.

docs/dashboard.html es auto-descriptivo: cada nodo con data-chart declara que
chart consume, con que overrides, que columna lee y como la colapsa. Parsear ese
HTML da el inventario completo de lo que el usuario ve, sin mantener a mano una
lista de 280 cards que se desactualizaria en la primera PR.

Se usa html.parser de la stdlib a proposito: bs4/lxml no estan instalados ni en
local ni en App Runner, y agregarlos por esto no se justifica.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field as dc_field
from html.parser import HTMLParser
from pathlib import Path

PROD_URL = "https://vinttihub.vintti.com/dashboard.html"
_REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_PATH = _REPO_ROOT / "docs" / "dashboard.html"

# control-dashboard.js:28 — lo que el front manda siempre, sin que el usuario toque nada.
FILTER_DEFAULTS = {
    "opp_stage": "Close Win",
    "window": "30d",
    "grain": "month",
    "subtab": "staffing",
}

# control-dashboard.js:4363 — una ventana de calendario se ancla a HOY y por eso
# anula el filtro Corte global. Sin esto los valores recalculados no coinciden
# con la pantalla en todas las sub-tiles "Last week / Last month / MTD".
CALENDAR_WINDOWS = {
    "week", "semana", "last_week", "last-week", "prev_week",
    "month", "last_month", "last-month", "prev_month", "mtd",
}

# control-dashboard.js:937 y :980 — el default de reduce depende del binding.
_DEFAULT_REDUCE = {"text": "last", "progress-fill": "first", "low-sample": "first"}

# Las 8 formas en que el HTML abre un panel del drawer. Si falta una, el panel
# queda mal marcado como huerfano.
OPENER_ATTRS = (
    "data-kpi-detail-open", "data-category-detail-open", "data-period-detail-open",
    "data-week-detail-panel", "data-bucket-detail-panel", "data-line-detail-panel",
    "data-detail-panel", "data-target-panel",
)

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

TITLE_CLASSES = (
    "kpi-drawer__title", "card__title", "skpi-tile__title", "hero-kpi__title",
    "skpi-header__title", "skpi-group__title", "ae-rows__name",
)
LABEL_CLASSES = (
    "kpi-drawer__hero__label", "kpi-drawer__stat__label", "kpi-drawer__section-title",
    "skpi-sub__label", "hero-kpi__label", "wrchan-bar__label", "ae-gmrr-stat__label",
    "bars__name",
)
# Un titulo vive dentro de un wrapper __head; hay que colgarlo del contenedor de
# la card para que los nodos hermanos lo encuentren como ancestro.
CONTAINER_HINTS = (
    "kpi-drawer__panel-content", "skpi-tile", "hero-kpi", "skpi-group", "skpi-header",
    "ae-rows", "wrchan-card", "accum-card", "ae-card", "card",
)


_TITLE_SET = frozenset(TITLE_CLASSES)
_LABEL_SET = frozenset(LABEL_CLASSES)
_CONTAINER_SET = frozenset(CONTAINER_HINTS)


@dataclass
class Node:
    """Un elemento del HTML que pide datos y pinta un numero."""
    chart_key: str
    bind: str
    field: str | None
    reduce: str
    fmt: str
    overrides: dict
    limit: int | None
    corte_field: str | None
    month_aware: str | None
    empty_text: str | None
    is_hero: bool
    line: int
    tab: str | None = None
    subtab: str | None = None
    panel: str | None = None
    panel_title: str | None = None
    card_title: str | None = None
    label: str | None = None
    _ancestors: list = dc_field(default_factory=list, repr=False)

    @property
    def filters(self) -> dict:
        """Filtros efectivos que el front mandaria por query string."""
        out = dict(FILTER_DEFAULTS)
        out.update(self.overrides)
        return {k: v for k, v in out.items() if v not in (None, "")}

    @property
    def comp_key(self) -> str:
        """Espejo de compKeyFor(): identidad de la peticion, para deduplicar."""
        items = sorted(self.filters.items())
        return self.chart_key + "?" + "&".join(f"{k}={v}" for k, v in items)

    def where(self) -> str:
        """Titulo de la card y que numero de esa card es, tal como se leen en pantalla.

        Sin la pestana: el reporte la muestra aparte y con el nombre real de la
        barra de navegacion, no con el slug interno.
        """
        bits = [b for b in (self.panel_title or self.card_title, self.label) if b]
        return " · ".join(bits) or self.chart_key

    @property
    def in_drawer(self) -> bool:
        """El numero vive dentro del panel de detalle, no en la card de la pestana."""
        return self.panel is not None


class _Frame:
    __slots__ = ("tag", "classes", "title", "label", "panel", "tab", "subtab")

    def __init__(self, tag, classes, panel, tab, subtab):
        self.tag = tag
        self.classes = classes
        self.title = None
        self.label = None
        self.panel = panel
        self.tab = tab
        self.subtab = subtab


class _DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[_Frame] = []
        self.nodes: list[Node] = []
        self.panels: dict[str, dict] = {}       # panel_key -> {title, line, frame}
        self.openers: dict[str, list] = {}      # panel_key -> [{tab, line, card}]
        self._capture = None                    # (owner, kind, elem_frame)
        self._buf: list[str] = []

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _overrides(a: dict) -> dict:
        """Espejo de readOverridesFor(): data-override-foo-bar -> {'foo_bar': valor}."""
        out = {}
        for name, value in a.items():
            if name.startswith("data-override-"):
                key = name[len("data-override-"):].replace("-", "_")
                if key:
                    out[key] = value
        if str(out.get("window", "")).strip().lower() in CALENDAR_WINDOWS:
            out["corte"] = ""
        return out

    def _inherited(self, attr):
        for f in reversed(self.stack):
            v = getattr(f, attr)
            if v:
                return v
        return None

    def _title_owner(self):
        """Contenedor de card al que pertenece un titulo (saltea el wrapper __head)."""
        for f in reversed(self.stack):
            if _class_tokens(f.classes) & _CONTAINER_SET:
                return f
        return self.stack[-1] if self.stack else None

    def _flush_capture(self):
        if not self._capture:
            return
        owner, kind, _elem = self._capture
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text and owner is not None and getattr(owner, kind) is None:
            setattr(owner, kind, text)
        self._capture = None
        self._buf = []

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = a.get("class", "")
        line = self.getpos()[0]

        panel = a.get("data-kpi-detail-panel") or self._inherited("panel")
        tab = a.get("data-channel") or self._inherited("tab")
        subtab = a.get("data-sub-channel") or self._inherited("subtab")
        frame = _Frame(tag, classes, panel, tab, subtab)

        if "data-kpi-detail-panel" in a:
            self.panels.setdefault(
                a["data-kpi-detail-panel"], {"title": None, "line": line, "frame": frame}
            )

        for attr in OPENER_ATTRS:
            if a.get(attr):
                self.openers.setdefault(a[attr], []).append(
                    {"tab": tab, "line": line, "card": self._inherited("title"), "via": attr}
                )

        if "data-chart" in a:
            bind = a.get("data-bind", "")
            self.nodes.append(Node(
                chart_key=a["data-chart"],
                bind=bind,
                field=a.get("data-field"),
                reduce=a.get("data-reduce") or _DEFAULT_REDUCE.get(bind, "last"),
                fmt=a.get("data-fmt", "number"),
                overrides=self._overrides(a),
                limit=int(a["data-limit"]) if (a.get("data-limit") or "").isdigit() else None,
                corte_field=a.get("data-corte-field"),
                month_aware=a.get("data-month-aware") if "data-month-aware" in a else None,
                empty_text=a.get("data-empty-text"),
                is_hero="kpi-drawer__hero__value" in _class_tokens(classes),
                line=line,
                _ancestors=list(self.stack) + [frame],
            ))

        # El texto del titulo/label se junta hasta que cierre SU tag, pero se
        # cuelga del contenedor (titulo) o del padre inmediato (label).
        tokens = _class_tokens(classes)
        if tokens & _TITLE_SET:
            self._flush_capture()
            self._capture = (self._title_owner(), "title", frame)
        elif tokens & _LABEL_SET:
            self._flush_capture()
            self._capture = (self.stack[-1] if self.stack else None, "label", frame)

        if tag not in VOID_TAGS:
            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self._close(tag)

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS:
            self._close(tag)

    def _close(self, tag):
        if self._capture and self.stack and self._capture[2] is self.stack[-1]:
            self._flush_capture()
        # HTML real trae tags desbalanceados; se desapila hasta el match y si no
        # existe se ignora, en vez de corromper el contexto de todo lo que sigue.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def _class_tokens(classes: str) -> set:
    """Clases como tokens exactos.

    Comparar por substring rompia el titulo de casi todas las cards: el hint
    "skpi-tile" matcheaba tambien a "skpi-tile__head", asi que el titulo se
    colgaba del wrapper del encabezado en vez de la card, y los numeros
    hermanos nunca lo encontraban como ancestro.
    """
    return set(classes.split())


def _resolve(parser: _DashboardParser) -> None:
    """Asigna a cada nodo el titulo/label/pestana de su ancestro mas cercano.

    Se hace despues de parsear porque el texto de un titulo recien se conoce al
    cerrar su tag, y para entonces los nodos que lo tienen como ancestro ya
    estan creados.
    """
    for info in parser.panels.values():
        info["title"] = info.pop("frame").title
        info["nodes"] = []

    for n in parser.nodes:
        anc = n._ancestors
        n.tab = next((f.tab for f in reversed(anc) if f.tab), None)
        n.subtab = next((f.subtab for f in reversed(anc) if f.subtab), None)
        n.panel = next((f.panel for f in reversed(anc) if f.panel), None)
        n.card_title = next((f.title for f in reversed(anc) if f.title), None)
        n.label = next((f.label for f in reversed(anc) if f.label), None)
        if n.panel and n.panel in parser.panels:
            info = parser.panels[n.panel]
            n.panel_title = info["title"]
            info["nodes"].append(n)
            # El drawer vive fuera de los .channel: la pestana de un nodo de
            # panel es la del boton que lo abre, no la de su posicion en el DOM.
            if not n.tab:
                n.tab = next(
                    (o["tab"] for o in parser.openers.get(n.panel, []) if o["tab"]), None
                )
        n._ancestors = []


@dataclass
class Topology:
    nodes: list
    panels: dict
    openers: dict
    source: str

    def by_panel(self, panel_key) -> list:
        return (self.panels.get(panel_key) or {}).get("nodes", [])

    def orphan_panels(self) -> list:
        """Paneles definidos que ningun boton abre: codigo muerto en la UI."""
        return sorted(k for k in self.panels if k not in self.openers)

    def dangling_openers(self) -> list:
        """Botones que apuntan a un panel inexistente: click que no hace nada."""
        return sorted(k for k in self.openers if k not in self.panels)

    def comp_keys(self) -> dict:
        """comp_key -> nodos que comparten esa misma peticion (dedupe de queries)."""
        out = {}
        for n in self.nodes:
            out.setdefault(n.comp_key, []).append(n)
        return out


def load_html() -> tuple[str, str]:
    """Devuelve (html, origen). Prioriza produccion; cae al repo local.

    Auditar el HTML servido y no el del working tree es deliberado: lo que la
    gente mira es GitHub Pages, y asi tambien se detecta un deploy que quedo
    apuntando a un chart_key que ya no existe.
    """
    if os.environ.get("DASHBOARD_AUDIT_HTML") == "local":
        return LOCAL_PATH.read_text(encoding="utf-8"), "local"
    try:
        import requests

        res = requests.get(PROD_URL, timeout=30)
        res.raise_for_status()
        return res.text, PROD_URL
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de red cae al local
        if not LOCAL_PATH.exists():
            raise RuntimeError(
                f"No se pudo bajar {PROD_URL} ({exc}) y no existe {LOCAL_PATH}"
            ) from exc
        return LOCAL_PATH.read_text(encoding="utf-8"), f"local (fallback: {exc})"


def build(html: str | None = None, source: str = "?") -> Topology:
    if html is None:
        html, source = load_html()
    parser = _DashboardParser()
    parser.feed(html)
    parser.close()
    parser._flush_capture()
    _resolve(parser)
    return Topology(
        nodes=parser.nodes, panels=parser.panels, openers=parser.openers, source=source
    )


# --- emparejado hero <-> detalle -------------------------------------------
# El numero grande del drawer y el contador de su lista salen de DATASETS
# DISTINTOS (*_kpi_* vs *_table_*_detail). Nada en el codigo obliga a que
# coincidan: el front solo cuenta filas. Emparejarlos es lo que permite
# detectar automaticamente "la card dice 12 y el detalle trae 9".

COUNT_REDUCES = {"count", "count-distinct"}
# Un hero de plata cuadra contra la SUMA de la columna de plata del detalle,
# no contra la cantidad de filas.
MONEY_FORMATS = {"currency", "currency-k"}
PERCENT_FORMATS = {"percent", "percent2", "percent-pp"}
# Solo un hero que sea una CANTIDAD puede compararse contra un conteo de filas.
# Un promedio de meses o un tiempo medio comparte nucleo de nombre con su
# detalle pero no tiene por que igualar su cantidad de filas.
COUNTABLE_FORMATS = {"int", "number"}
_NON_COUNT_FIELD = re.compile(r"avg|prom|mean|median|months|days|dias|time|tiempo|rate|pct")

_STEM_RE = re.compile(
    r"^(?:sa|am|gr|op|mk|ae|mg)_"
    r"(?:kpi|table|line|bar|bars|area|donut|rank|stack|select|funnel|tile)_"
)


def dataset_stem(chart_key: str) -> str:
    """Nucleo de la metrica: am_kpi_client_churn_30d -> client_churn_30d.

    El repo nombra card y detalle con el mismo nucleo (foo / foo_detail), asi
    que comparar nucleos es la senal mas confiable para saber que un contador
    del drawer corresponde a ese hero y no a otra metrica del mismo panel.
    """
    stem = _STEM_RE.sub("", chart_key)
    for suf in ("_detail", "_full", "_repl"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    return stem


@dataclass
class Pair:
    panel: str
    panel_title: str
    hero: Node
    detail: Node
    confidence: str          # "strong" (nucleos iguales) | "weak" (unico candidato)

    @property
    def kind(self) -> str:
        return "sum" if self.detail.reduce == "sum" else "count"

    def describe(self) -> str:
        return (
            f"{self.panel_title or self.panel}: hero "
            f"{self.hero.chart_key}[{self.hero.field}] vs detalle "
            f"{self.detail.chart_key} ({self.detail.reduce}"
            + (f"[{self.detail.field}]" if self.detail.field else "")
            + ")"
        )


def _window_of(node) -> str:
    return str(node.filters.get("window", ""))


def hero_detail_pairs(topo) -> list:
    """Pares (hero, contador-del-detalle) comparables dentro de cada panel.

    Solo se emparejan nodos de la MISMA ventana y de datasets distintos: si
    fueran el mismo dataset la comparacion seria trivialmente cierta.

    Un hero porcentual nunca se compara contra un conteo de filas: un 47% no
    tiene por que ser igual a 47 filas, y hacerlo llenaba el reporte de ruido.
    """
    pairs = []
    for panel_key, info in topo.panels.items():
        nodes = info.get("nodes") or []
        heroes = [n for n in nodes if n.is_hero and n.field]
        if not heroes:
            continue
        for hero in heroes:
            if hero.fmt in PERCENT_FORMATS:
                continue
            wants_money = hero.fmt in MONEY_FORMATS
            countable = (
                hero.fmt in COUNTABLE_FORMATS
                and not _NON_COUNT_FIELD.search(hero.field or "")
            )
            if not wants_money and not countable:
                continue
            hero_stem = dataset_stem(hero.chart_key)
            cands = []
            for cand in nodes:
                if cand.bind != "text" or cand.chart_key == hero.chart_key:
                    continue
                if _window_of(cand) != _window_of(hero):
                    continue
                is_count = cand.reduce in COUNT_REDUCES
                is_sum = cand.reduce == "sum" and cand.field
                if (wants_money and is_sum) or (not wants_money and is_count):
                    cands.append(cand)
            if not cands:
                continue
            strong = [c for c in cands if dataset_stem(c.chart_key) == hero_stem]
            if strong:
                pairs.extend(Pair(panel_key, info.get("title"), hero, c, "strong")
                             for c in strong)
            elif len(cands) == 1:
                # Sin coincidencia de nombre pero hay un unico candidato en el
                # panel: probablemente es el par, pero se marca debil para que
                # el reporte no lo trate como error confirmado.
                pairs.append(Pair(panel_key, info.get("title"), hero, cands[0], "weak"))
    return pairs
