# Concello a partir de coordenadas

Fecha: 2026-09-26. Validación para la decisión D7 de [diseno.md](diseno.md).

## Problema

Todo lo público de MeteoGalicia va por `idConcello`, pero ningún endpoint público da coordenadas de concello. Las estaciones (`listaEstacionsMeteo`) sí traen coordenadas, pero son 155 en 130 concellos: no sirven para deducir el concello de cualquier punto. MeteoSIX pedido por coordenadas tampoco devuelve el concello.

## Fuente

Servicio WFS de unidades administrativas del [IGN](https://www.ign.es) (CC BY 4.0), a resolución completa, generado con `scripts/generate_data.py`:

- Los **313 concellos de Galicia**, con su código INE, que coincide con el `idConcello` de MeteoGalicia.
- Los **36 municipios de Asturias, León y Zamora** que están a menos de 3 km de Galicia, para saber que un punto está fuera.
- Simplificados a **~100 m**, con 4 decimales: **465 KB**. En memoria, ~4 MB y 50 ms de carga; solo se usa en la configuración.

La primera versión usaba es-atlas (IGN cuantizado a ~180 m, 110 KB) y acertaba 146 de 155.

## Tolerancia elegida

| Tolerancia | Tamaño | Estaciones correctas |
|---|---|---|
| 20 m | 1.303 KB | 151 |
| 50 m | 748 KB | 152 |
| **100 m** | **465 KB** | **152** |
| 150 m | 345 KB | 152 |

Con 100 m, la mitad de error en los límites que con 150 m por 120 KB más.

## Validación con las 155 estaciones

Cada estación trae su concello. Es un caso difícil: muchas están en cabos, puertos o cumbres que hacen de límite.

**152 de 155.** Los 3 fallos:

| Estación | MeteoGalicia | Nosotros | IGN a resolución completa |
|---|---|---|---|
| Fragavella | Abadín | Mondoñedo | Mondoñedo: error de MeteoGalicia |
| Xinzo | Xinzo de Limia | Sandiás | Sandiás: error de MeteoGalicia |
| Río do Sol | Coristanco | Tordoia | Coristanco: pegada al límite |

Ojo al comparar nombres: la lista de concellos de MeteoGalicia escribe "Fonsagrada (A)" y la de estaciones "A FONSAGRADA". Usar siempre el código, nunca el nombre.

## Reglas

1. Punto dentro de un concello → ese concello.
2. Si no, y está dentro de un municipio vecino (Asturias, León, Zamora) a más de 250 m de Galicia → fuera. Los 250 m cubren el solape de contornos simplificados por separado.
3. Si no, el concello más cercano a menos de 2 km (mar, puertos, islas).
4. Si no, fuera de Galicia.

Portugal no está en los datos: un punto portugués a menos de 2 km de un concello (por ejemplo, Valença frente a Tui) se asigna a ese concello. El usuario lo ve al confirmar.

## Mantenimiento

- La última fusión de concellos en Galicia fue en 2016. Si hubiera otra, basta con volver a ejecutar el script.
- Todo se muestra en un formulario de confirmación, donde el usuario puede corregirlo.
