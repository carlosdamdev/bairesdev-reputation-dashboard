/**
 * BairesDev Social Scoring — Actualización Week 19 (2026-05-04)
 *
 * Instrucciones:
 *   1. Abrir el Google Sheet
 *   2. Extensiones > Apps Script
 *   3. Pegar este código (reemplazar todo el contenido)
 *   4. Guardar (Ctrl+S)
 *   5. Seleccionar función "updateWeek19" y hacer click en ▶ Ejecutar
 *   6. Aceptar permisos la primera vez
 *   7. Ver el log en Vista > Registros de ejecución
 */

function updateWeek19() {
  var ss   = SpreadsheetApp.getActiveSpreadsheet();
  var WEEK = 19;

  // ── Datos scrapeados 2026-05-04 ─────────────────────────────────────────────
  var SCORES = {
    Trustpilot: 4.4,
    Clutch:     4.9,
    Glassdoor:  4.2,
    TeamBlind:  4.1,
    Indeed:     4.0,
  };
  var NEW_REVIEWS = {
    Trustpilot: '-',
    Clutch:     '-',
    Glassdoor:  '-',
    TeamBlind:  '-',
    Indeed:     1,      // subió de 134 → 135
  };
  var TOTAL_REVIEWS = {
    Trustpilot: 174,
    Clutch:     62,
    Glassdoor:  null,   // discrepancia entre fuentes — no tocar
    TeamBlind:  25,
    Indeed:     135,
  };

  // ── 1. Tabs de plataforma ────────────────────────────────────────────────────
  ['Trustpilot', 'Clutch', 'Glassdoor', 'TeamBlind', 'Indeed'].forEach(function(name) {
    var sheet = ss.getSheetByName(name);
    if (!sheet) { Logger.log('⚠  Tab no encontrada: ' + name); return; }
    updatePlatformTab(sheet, WEEK, SCORES[name], NEW_REVIEWS[name], TOTAL_REVIEWS[name]);
  });

  // ── 2. Tab Report 2026 ───────────────────────────────────────────────────────
  var reportSheet = ss.getSheetByName('Report 2026');
  if (!reportSheet) {
    Logger.log('Tabs disponibles: ' + ss.getSheets().map(function(s){return s.getName();}).join(', '));
    Logger.log('⚠  Tab "Report 2026" no encontrada — revisá el nombre exacto arriba');
  } else {
    updateReportTab(reportSheet, WEEK, SCORES);
  }

  SpreadsheetApp.flush();
  Logger.log('✓ Listo');
}

// ── Actualiza una tab de plataforma individual ──────────────────────────────────
function updatePlatformTab(sheet, week, score, newRevs, totalRevs) {
  var data = sheet.getDataRange().getValues();

  // Buscar la fila de encabezado "Week | Score | New Reviews"
  var headerRow = -1;
  for (var i = 0; i < data.length; i++) {
    if (String(data[i][0]).trim().toLowerCase() === 'week') {
      headerRow = i; // 0-indexed
      break;
    }
  }
  if (headerRow < 0) { Logger.log('⚠  Sin encabezado "Week" en: ' + sheet.getName()); return; }

  // Ver si la semana ya existe
  for (var r = headerRow + 1; r < data.length; r++) {
    if (Number(data[r][0]) === week) {
      sheet.getRange(r + 1, 2).setValue(score);
      sheet.getRange(r + 1, 3).setValue(newRevs);
      Logger.log('✓ ' + sheet.getName() + ': Week ' + week + ' actualizada (ya existía)');
      return;
    }
  }

  // Insertar fila nueva justo después del encabezado (filas más recientes arriba)
  var insertRow1 = headerRow + 2; // 1-indexed
  sheet.insertRowBefore(insertRow1);
  sheet.getRange(insertRow1, 1).setValue(week);
  sheet.getRange(insertRow1, 2).setValue(score);
  sheet.getRange(insertRow1, 3).setValue(newRevs);
  Logger.log('✓ ' + sheet.getName() + ': Week ' + week + ' insertada en fila ' + insertRow1 + ' (score=' + score + ', new=' + newRevs + ')');

  // Actualizar Total Reviews si tenemos el dato
  if (totalRevs !== null) {
    var freshData = sheet.getDataRange().getValues();
    for (var r = 0; r < freshData.length; r++) {
      var cell = String(freshData[r][0]);
      if (cell.indexOf('Total Reviews') >= 0 && cell.indexOf('2026') < 0) {
        sheet.getRange(r + 1, 2).setValue(totalRevs);
        Logger.log('✓ ' + sheet.getName() + ': Total Reviews → ' + totalRevs);
        break;
      }
    }
  }
}

// ── Actualiza el tab Report 2026 ───────────────────────────────────────────────
function updateReportTab(sheet, week, scores) {
  var data    = sheet.getDataRange().getValues();
  var numRows = data.length;
  var numCols = data[0] ? data[0].length : 0;
  var weekLabel = 'Week ' + week;

  // Recorre cada fila buscando filas de encabezado que tengan "Week X"
  for (var r = 0; r < numRows; r++) {

    // ¿Esta fila tiene encabezados de semana?
    var weekCols    = {};  // { weekNum: colIndex_0based }
    var maxWeekNum  = -1;
    var maxWeekCol  = -1;

    for (var c = 0; c < numCols; c++) {
      var cell = String(data[r][c]);
      var m = cell.match(/^Week (\d+)$/);
      if (m) {
        var wn = parseInt(m[1]);
        weekCols[wn] = c;
        if (wn > maxWeekNum) { maxWeekNum = wn; maxWeekCol = c; }
      }
    }

    if (maxWeekNum < 0) continue; // Esta fila no tiene encabezados de semana

    // Columna donde va Week 19
    var weekCol19;
    if (weekCols[week] !== undefined) {
      weekCol19 = weekCols[week]; // 0-indexed
    } else {
      // Agregar columnas faltantes (week+1 … week) después de la última
      for (var wk = maxWeekNum + 1; wk <= week; wk++) {
        var newCol = maxWeekCol + (wk - maxWeekNum) + 1; // 1-indexed
        sheet.getRange(r + 1, newCol).setValue('Week ' + wk);
        Logger.log('Report 2026: columna "Week ' + wk + '" creada en col ' + newCol);
      }
      weekCol19 = maxWeekCol + (week - maxWeekNum); // 0-indexed
      // Refrescar data para las filas de abajo
      data = sheet.getDataRange().getValues();
      numCols = data[0] ? data[0].length : 0;
    }

    var targetCol1 = weekCol19 + 1; // 1-indexed para getRange

    // Recorrer filas de la tabla y actualizar las que corresponden a plataformas
    for (var dr = r + 1; dr < numRows; dr++) {
      var label0 = String(data[dr][0]).trim();
      var label1 = String(data[dr][1]).trim();

      // Fin de tabla: fila vacía
      if (label0 === '' && label1 === '') break;

      // Tabla con "Platform | Week0 | Week1 ..." (col A es el nombre de plataforma)
      if (scores[label0] !== undefined) {
        sheet.getRange(dr + 1, targetCol1).setValue(scores[label0]);
        Logger.log('Report 2026 [Platform table]: ' + label0 + ' Week ' + week + ' = ' + scores[label0]);
      }

      // Tabla con "Clutch | Score | 4.9 | ..." (col A = plataforma, col B = "Score")
      if (scores[label0] !== undefined && label1 === 'Score') {
        sheet.getRange(dr + 1, targetCol1).setValue(scores[label0]);
        Logger.log('Report 2026 [Score row]: ' + label0 + ' Week ' + week + ' = ' + scores[label0]);
      }
    }
  }
  Logger.log('✓ Report 2026 actualizado para Week ' + week);
}
