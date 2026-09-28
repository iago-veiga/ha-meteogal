# Imagen de MeteoGal

- `icon.svg` y `dark_icon.svg` son el origen de los PNG de `custom_components/meteogal/brand/`.
- Contorno de Galicia simplificado a partir de `spain-communities.geojson` de [click_that_hood](https://github.com/codeforgermany/click_that_hood) (MIT).
- No hay `logo.png`: el logo es cuadrado, así que HA usa el icono en su lugar.

Para regenerar los PNG (256 y 512 px, optimizados y entrelazados):

```sh
B=custom_components/meteogal/brand
for v in icon dark_icon; do
  rsvg-convert -w 256 -h 256 docs/brand/$v.svg -o $B/$v.png
  rsvg-convert -w 512 -h 512 docs/brand/$v.svg -o "$B/$v@2x.png"
done
optipng -o7 -i1 $B/*.png
```
