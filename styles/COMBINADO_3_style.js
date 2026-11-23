var size = 0;
var placement = 'point';

function crearEstiloLote(fillColor, feature, resolution, labelText, labelFont, labelFill, bufferColor, bufferWidth, placement) {
    return [new ol.style.Style({
        stroke: new ol.style.Stroke({
            color: 'rgba(35,35,35,0.575)',
            lineDash: null,
            lineCap: 'butt',
            lineJoin: 'miter',
            width: 0.988
        }),
        fill: new ol.style.Fill({ color: fillColor }),
        text: createTextStyle(
            feature, resolution, labelText, labelFont,
            labelFill, placement, bufferColor, bufferWidth
        )
    })];
}

function normalizarEstado(value) {
    if (value === null || value === undefined) return 'DEFAULT';
    return value
        .toString()
        .trim()
        .toUpperCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, ''); // Quita tildes (ej: PÚBLICO -> PUBLICO, SEÑADO -> SENADO)
}

function categories_COMBINADO_3(feature, value, size, resolution, labelText,
                       labelFont, labelFill, bufferColor, bufferWidth,
                       placement) {
    var estado = normalizarEstado(value);
    var color = 'rgba(0,0,0,0.575)'; // Default (negro) para estados desconocidos

    switch (estado) {
        // --- Estados principales (mismos colores que tu mapa actual) ---
        case 'VENDIDO':
            color = 'rgba(29,84,255,0.575)';       // Azul
            break;
        case 'LIBRE':
            color = 'rgba(104,232,12,0.575)';      // Verde brillante
            break;
        case 'RESERVA DE PROPIETARIO':
        case 'P':                                  // Código APEX que coincide mayormente con Reserva de propietario
        case 'RETIRADO POR EL PROP.':
            color = 'rgba(242,251,0,0.575)';       // Amarillo
            break;
        case 'RECUPERADO':
            color = 'rgba(30,226,255,0.575)';      // Celeste
            break;
        case 'CANCELADO':
            color = 'rgba(251,0,0,0.575)';         // Rojo
            break;
        case 'ANULADO':
        case 'N':                                  // Código APEX de no disponible / anulado
            color = 'rgba(255,127,0,0.575)';       // Naranja
            break;
        case 'PLAZA':
        case 'AREA VERDE':
            color = 'rgba(6,105,0,0.575)';         // Verde oscuro
            break;
        case 'EDIFICIO PUBLICO':
            color = 'rgba(4,89,0,0.575)';          // Verde muy oscuro
            break;
        case 'RESERVA':
        case 'RESERVADO':
            color = 'rgba(128,0,128,0.575)';       // Violeta
            break;

        // --- Estados adicionales del desplegable de Oracle APEX ---
        case 'VENDIDO POR PROP.':
            color = 'rgba(15,48,170,0.575)';       // Azul oscuro
            break;
        case 'VENTAS SIN LEGAJO':
            color = 'rgba(80,125,255,0.575)';      // Azul claro
            break;
        case 'SENADO':
            color = 'rgba(186,85,211,0.575)';      // Lila / Orquídea
            break;
        case 'ABOGADO':
            color = 'rgba(139,0,0,0.575)';         // Bordó / Rojo oscuro
            break;
    }

    return crearEstiloLote(
        color, feature, resolution, labelText,
        labelFont, labelFill, bufferColor, bufferWidth, placement
    );
}

var style_COMBINADO_3 = function(feature, resolution) {
    var labelText = "";
    var value = feature.get("Estado");
    var labelFont = "9.0px 'Rockwell Extra Bold', sans-serif";
    var labelFill = "#ffffff";
    var bufferColor = "#000000";
    var bufferWidth = 2.0;
    var placement = 'point';

    if (feature.get("Lote") !== null && resolution > 0 && resolution < 2) {
        labelText = String(feature.get("Lote"));
    }

    return categories_COMBINADO_3(
        feature, value, size, resolution, labelText,
        labelFont, labelFill, bufferColor, bufferWidth, placement
    );
};
