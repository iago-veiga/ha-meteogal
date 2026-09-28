# Nombres de concello

Fecha: 2026-09-27.

## Norma

- Al usuario se le habla siempre igual. Los textos de la interfaz son nuestros y los traducimos nosotros (gl, es, en).
- Los concellos se muestran siempre con su **topónimo oficial**, que es la forma gallega (Lei 3/1983 de normalización lingüística, art. 10). Los topónimos no se traducen: "A Coruña" es igual en los tres idiomas.
- Nunca se muestra un nombre de concello que venga de la API de MeteoGalicia. Todo se identifica por código INE.

## Fuente

[Nomenclátor de Galicia](https://abertos.xunta.gal/catalogo/territorio-vivienda-transporte/-/dataset/0270/nomenclator-galicia) de la Xunta (CC BY-SA 4.0), versión aprobada el 30 de marzo de 2026. Cambió el nombre de 12 concellos (A Cañiza → A Caniza, Cangas → Cangas de Morrazo, Porto do Son → O Porto do Son, etc.).

El CSV no trae código INE y da los nombres en mayúsculas con el artículo detrás ("BAÑA, A"). `scripts/generate_data.py`:

1. Empareja cada concello con su código INE a través de los nombres del IGN, admitiendo el nombre anterior a 2026. Los 313 salen sin ambigüedad.
2. Pone el artículo delante y las mayúsculas en su sitio ("A Baña", "San Cibrao das Viñas").
3. Comprueba el resultado: los 313 nombres coinciden letra a letra con los del IGN actual.

Resultado: `custom_components/meteogal/data/toponimos.json`, cargado con `load_toponyms()`. Por la licencia CC BY-SA, ese fichero se distribuye con la misma licencia (ver `NOTICE`); el código sigue en Apache 2.0.

## Nombres de estación y de cámara

Los da MeteoGalicia («Coruña-Torre de Hércules», «Porto de Vigo») y no hay otra fuente oficial: se muestran tal cual en la configuración, en los atributos y en las reparaciones. El concello que acompaña a cada estación o cámara en las listas sí sale del Nomenclátor, por su código.
