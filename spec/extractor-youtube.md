# Especificación — Extractor de Fragmentos de YouTube

> **Historia de Usuario:**
> Como usuario quiero poder pegar una url de un video de youtube en una interfaz y quiero poder definir un rango de tiempo inicio y fin para extraer ese fragmento de video y descargarlo en mi direccitorio de descarga o cualquier otra ruta de descarga.

**Fecha de creación:** 2026-05-29
**Estado:** Definida
**Prioridad:** Por definir

---

## 1. Descripción General
Esta herramienta proporciona una interfaz sencilla para que los usuarios puedan generar y descargar fragmentos específicos (clips) de videos de YouTube. Permite ingresar una URL, configurar un rango de tiempo exacto, elegir parámetros de salida (formato MP4 o GIF y calidad entre 360p y 1080p) y guardar el archivo resultante localmente a través del gestor de descargas estándar del sistema.

---

## 2. Alcance

### 2.1 Incluido en esta fase
- Soporte para URLs convencionales y YouTube Shorts.
- Previsualización automática de información del video (miniatura, título, duración).
- Controles sincronizados para selección de tiempo (slider visual e inputs `HH:MM:SS`).
- Selección de formato de salida: MP4 o GIF.
- Selección dinámica de calidad de vídeo (desde 360p hasta 1080p, consultando disponibilidad).
- Límite de extracción fijado en un máximo de 15 minutos por fragmento.
- Corrección automática de tiempos fuera de rango (ej. límite de fin superior a la duración total).
- Barra de progreso de procesamiento.

### 2.2 Excluido de esta fase
- Descarga de videos completos.
- Extracción de audio exclusivamente (ej. MP3).
- Soporte para videos privados, eliminados o con restricciones de inicio de sesión.
- Edición avanzada de video (transiciones, recortes de encuadre, subtítulos).

---

## 3. Actores
| Actor | Descripción |
|-------|-------------|
| **Usuario Estándar** | Cualquier persona que acceda a la interfaz web/aplicación para recortar y descargar un fragmento de video de YouTube. |

---

## 4. Precondiciones
- Disponer de acceso a internet.
- El enlace (URL) proporcionado debe ser de un video de YouTube público y disponible.

---

## 5. Flujos

### 5.1 Flujo Principal — Extracción exitosa
1. El usuario pega una URL de YouTube válida en el campo de entrada principal.
2. El sistema valida la URL automáticamente en segundo plano.
3. El sistema muestra la miniatura, título y duración del video.
4. El sistema consulta y despliega las calidades disponibles para ese video (entre 360p y 1080p).
5. Se habilitan los controles de recorte temporal y los selectores de formato/calidad.
6. El usuario ajusta el inicio y el fin (usando el slider o los campos de texto).
7. El usuario selecciona el formato (MP4 o GIF) y la resolución deseada.
8. El usuario hace clic en "Extraer" (o "Descargar").
9. El sistema bloquea el formulario e inicia el procesamiento, mostrando una barra de progreso porcentual.
10. Finalizado el procesamiento, se activa el diálogo estándar de descarga del sistema para guardar el archivo.
11. Se restablece la interfaz (o muestra éxito) para una nueva extracción.

### 5.2 Flujo Alternativo A — URL Inválida o Inaccesible
1. El usuario pega una URL (ej. privada, borrada o malformada).
2. El sistema intenta validarla.
3. El sistema detecta el error y muestra un mensaje explícito ("El video es privado o la URL no es válida") bajo el campo de texto.
4. Los controles de recorte temporal y descarga se mantienen deshabilitados.

### 5.3 Flujo Alternativo B — Corrección Temporal de Límite
1. El usuario introduce manualmente (en la caja `HH:MM:SS`) un tiempo de fin mayor que la duración real del video.
2. Al perder el foco el input (o intentar deslizar), el sistema corrige automáticamente ajustando el valor de fin al último segundo válido del video.

---

## 6. Configuración y Parámetros
- **Formatos Soportados:** MP4, GIF.
- **Calidades Soportadas:** 360p, 480p, 720p, 1080p (Dinámico según disponibilidad).
- **Límite Máximo de Segmento:** 15 minutos (900 segundos).

---

## 7. Validaciones

### 7.1 Validación en tiempo real (frontend)
| Campo | Regla | Mensaje de error |
|-------|-------|------------------|
| **URL Input** | Formato de URL de YouTube válido. | "Por favor, ingresa un enlace de YouTube válido." |
| **Tiempo Inicio** | Debe ser >= 0 y < Tiempo Fin. | (Se autolocaliza dinámicamente o deshabilita botón) |
| **Tiempo Fin** | Debe ser <= Duración Total. | (Autocorrección visual aplicada) |
| **Rango Total** | Tiempo Fin - Tiempo Inicio <= 15 min. | "El fragmento no puede durar más de 15 minutos." |

### 7.2 Validación en el servidor/backend (o script)
| Validación | Mensaje de error |
|------------|------------------|
| **Disponibilidad** | "El video no está disponible (privado, eliminado o restringido)." |
| **Límite Máximo** | "El segmento solicitado excede el límite permitido por el servidor." |
| **Calidad Elegida** | "La resolución seleccionada no está disponible para este video." |

---

## 8. Componentes de Interfaz

### 8.1 Pantalla Principal
- **Input text URL:** Campo grande y visible para pegar el enlace.
- **Card Vista Previa:** Contenedor de miniatura, título corto y etiqueta de duración total (se muestra tras cargar la URL).
- **Slider Rango Dual:** Barra deslizante con dos manijas (inicio y fin).
- **Inputs Horarios (x2):** Dos cajas de entrada (Inicio/Fin) con formato `HH:MM:SS`.
- **Select Formato:** Menú desplegable `[MP4, GIF]`.
- **Select Resolución:** Menú desplegable poblado dinámicamente `[1080p, 720p, 480p, 360p]`.
- **Botón "Extraer":** Acción principal para iniciar el proceso.
- **Barra de Progreso:** Elemento lineal que indica el porcentaje actual del procesamiento del video una vez iniciada la extracción.

---

## 9. Criterios de Aceptación
- [ ] La interfaz detecta automáticamente cuándo se pega una URL para comenzar a cargar la metadata, sin requerir click adicional de carga.
- [ ] La aplicación maneja correctamente enlaces estándar y de tipo "/shorts".
- [ ] El deslizador y las cajas de texto de tiempo están sincronizados bidireccionalmente en todo momento.
- [ ] Hay un límite inquebrantable de 15 minutos para cualquier extracción.
- [ ] Las opciones de calidad desplegadas corresponden estrictamente a las resoluciones menores o iguales a 1080p que realmente están disponibles en el video de origen.
- [ ] Al seleccionar GIF, la salida final es correctamente codificada y descargada como archivo de imagen animada.
- [ ] El sistema delega correctamente en la ventana de OS / Navegador del usuario para seleccionar dónde guardar el archivo generado.
- [ ] Si ocurre un error de procesamiento, este se muestra y se retira el bloqueo del formulario para reintentar.
