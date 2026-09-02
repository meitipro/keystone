# Brand

A small, fixed set of assets. Everything is SVG except the social card, which
GitHub needs as a raster.

| File | What it is | Where it goes |
|---|---|---|
| [`mark.svg`](mark.svg) | The mark alone, 100 x 100 | favicon, avatar, anything under 200px |
| [`lockup.svg`](lockup.svg) | Mark plus wordmark | README header, slides, docs |
| [`social.svg`](social.svg) | 1280 x 640 source | edit this, then re-export |
| [`social.png`](social.png) | 1280 x 640 export | Settings -> General -> Social preview |

## The mark

A wedge over the span it holds.

The keystone is the stone an arch cannot stand without, and this contract is the
only thing in the system that holds every pairwise judgment at once. Remove it
and each edge is still individually agreed; together they are no longer an
ordering. The chalk line beneath is the span - present, and dependent.

Built on a 100 x 100 grid. Stroke weight 8, mitred joins, corner radius 18. The
span is chalk at 4, thinner than the wedge and in a different colour, so it
reads as what is being carried rather than as part of the stone.

- **Clear space:** half the mark height on every side.
- **Smallest size:** 18px alone, 24px locked to the wordmark. Verified - the
  wedge taper and the span stay separable.
- **Never:** a second hue, a gradient, an outline version, a drop shadow, or the
  mark inverted. A wedge pointing the other way is not a keystone.

## Palette

| Token | Hex | Use |
|---|---|---|
| ink | `#0C0D10` | the mark's field, any dark surface |
| chalk | `#E8E6E1` | the wordmark, primary text, the span. Never pure white |
| accent | `#3DBFD6` | the mark, one primary action, one live state |
| muted | `#9AA0A8` | secondary text |
| rule | `#232830` | hairlines and dividers |

One accent, used sparingly. On the social card it appears exactly three times:
the top bar, the mark, and the footer line.

The accent is distinct from its siblings on purpose: Crosscheck is violet
`#8B7CF6`, Tolerance green `#3DD68C`, Recant coral `#E0645C`, and this one
cyan `#3DBFD6`. Same grid, same stroke language, same lockup geometry, different
hue - so the set reads as one hand without reading as one product.

## Type

**Inter**, weights 400 and 700, tracking tightened to -1.4 on the wordmark and
-2.6 at display size. Monospace for anything that is a value rather than a
sentence: `ui-monospace, SFMono-Regular, Menlo, monospace`. The wordmark is
always lowercase.

## Re-exporting the social card

The native cairo backend that `cairosvg` and `reportlab` both want is not
installed on every machine, so the card here was rasterised through a browser
canvas at 1280 x 640 and written back as PNG. Where cairo IS available:

```bash
pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='brand/social.svg',     write_to='brand/social.png', output_width=1280, output_height=640)"
```

Upload under **Settings -> General -> Social preview**. GitHub uses it whenever
a link to this repository is shared.

## Licence

MIT along with the rest of the repository. The name and mark identify this
specific primitive, so if you fork it and change what it does, change the name
too.
