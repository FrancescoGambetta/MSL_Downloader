# Guía MSL Image Downloader (ES)

Esta guía está pensada para alguien que descarga el proyecto desde GitHub y quiere:
1) instalar la app, 2) iniciarla, 3) entender qué ve en pantalla, 4) usarla para filtrar y descargar/procesar imágenes.

> **Nota importante**
> - Este proyecto se ha desarrollado y usado principalmente con **Anaconda/Conda**.
> - El procedimiento con `python -m venv` + `pip` se incluye como alternativa, pero **puede no haberse probado a fondo todavía** en todas las máquinas.

## 1) Qué es MSL Image Downloader
MSL Image Downloader es una app para buscar, descargar y organizar imágenes de la misión Mars Science Laboratory (Curiosity) de la NASA. Al abrirla se entra primero en una pantalla donde introduces tu nombre, y luego llegas a la app en sí, dividida en dos secciones que puedes elegir en cualquier momento desde arriba:

- **Downloader**: busca, filtra y descarga imágenes.
- **Catálogos (Catalog Manager)**: gestiona el catálogo local en el que se basa la búsqueda del Downloader (estado, actualizaciones desde la NASA, verificación, etc.).

El catálogo se descarga automáticamente en el primer arranque, sin necesidad de ningún paso manual.

## 2) Requisitos
- **Python**: se recomienda **3.11 o 3.12**
- **Conda**: recomendado (reduce problemas con librerías "binarias" como `pyarrow`)
- Conexión a internet: necesaria para descargar/actualizar el catálogo y para descargar algunos archivos externos (si procede)

> **Nota técnica**: `numpy` está fijado a `<2` por compatibilidad con `pyarrow` en algunos entornos.

## 3) Instalación (paso a paso) — Windows

> Esta sección trata la instalación **en Windows**.

### 3.1 Descarga el proyecto
Opción A (Git):
```bash
mkdir NOMBRE_CARPETA
cd NOMBRE_CARPETA
git clone <URL_REPO> .
```

Opción B (ZIP desde GitHub):
- descarga el ZIP
- extráelo en una carpeta (p. ej. `C:\Users\...\dwnapp`)
- abre una terminal dentro de la carpeta extraída

### 3.2 Crea el entorno (recomendado: Conda)
Desde la raíz del repositorio:
```bash
conda env create -f environment.yml
conda activate dwnapp
```

Nota sobre `environment.yml`:
- `environment.yml` crea el entorno (Python + pip) y luego instala las librerías mediante `pip -r requirements.txt`.
- En otras palabras: **la lista de dependencias está en `requirements.txt`**, mientras que el YAML sirve para crear un entorno limpio y coherente.

Alternativa (venv + pip):
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4) Iniciar la app
Para simplificar el inicio se ha creado un único archivo: basta con abrirlo (doble clic, en Windows) y la aplicación se inicia sola.

Doble clic en `launchers/Avvia_MSL_App.bat`: abre el navegador en `http://localhost:5173` cuando todo está listo.

## 5) Qué se ve en la interfaz (tour rápido)
Tras iniciar sesión se abre primero la sección **Catálogos**, para descargar y, si se quiere, personalizar el catálogo local. Una vez completado el asistente de instalación, se pasa al **Downloader** desde el selector de arriba.

En el Downloader la interfaz se divide en áreas:
- **Barra lateral** (a la izquierda): filtros, selección actual, botones de control
- **Área central**: resultados de la búsqueda
- **Vista previa/Metadatos**: vista previa de la imagen y metadatos asociados
- **Registro en vivo**: muestra el progreso y los mensajes durante la descarga

La carpeta de salida se puede elegir desde Ajustes, arriba a la derecha.

## 6) Cómo usar la app (flujo típico)
Un flujo típico:
1) Configurar la carpeta de salida/descarga
2) Aplicar filtros (sol, cámara, etc.)
3) Revisar la selección (cuántas imágenes, qué contiene)
4) Ejecutar **descarga** o **proceso**

### 6.1 Configurar la carpeta de salida
Si la app indica que falta la carpeta de salida:
- usa la opción para elegir la carpeta (diálogo) o define una ruta manual (ver ejemplos abajo)
- luego reintenta la descarga/proceso

### 6.2 Filtrar el catálogo
Puedes filtrar por:
- **sol** (rango o valor único)
- **cámara**
- (opcional) tamaño mínimo, variantes, tokens y otros filtros disponibles

### 6.3 Descargar o procesar
Comportamiento general:
- **Descarga**: guarda los archivos en bruto (normalmente `.IMG` + `.LBL`) en la carpeta de salida
- **Proceso/Conversión**: produce la salida final (normalmente `.jpg` + `.meta.json`) en la carpeta de salida
