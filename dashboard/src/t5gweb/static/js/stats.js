// Hide all datasets in chart
$("#hide-stats").click(function () {
  statsChart.data.datasets.forEach((element, index) => {
    statsChart.setDatasetVisibility(index, false);
  });
  statsChart.update();
});

// Show all datasets in chart
$("#show-stats").click(function () {
  statsChart.data.datasets.forEach((element, index) => {
    statsChart.setDatasetVisibility(index, true);
  });
  statsChart.update();
});

// First table requires natural sort, so initialize separately
$(document).ready(function () {
  $("#overall").DataTable({
    paging: false,
    info: false,
    searching: false,
    columnDefs: [{ type: "natural-nohtml", targets: 1 }],
  });
});

// Sort Severities Correctly (https://datatables.net/examples/plug-ins/sorting_auto.html)
$.fn.dataTable.ext.type.detect.unshift(function (d) {
  return d === "Low" || d === "Normal" || d === "High" || d === "Urgent"
    ? "severity-grade"
    : null;
});

$.fn.dataTable.ext.type.order["severity-grade-pre"] = function (d) {
  switch (d) {
    case "Low":
      return 1;
    case "Normal":
      return 2;
    case "High":
      return 3;
    case "Urgent":
      return 4;
  }
  return 0;
};

// Sort severity table from Urgent -> Low
$(document).ready(function () {
  $("#severity").DataTable({
    paging: false,
    info: false,
    searching: false,
    order: [[0, "desc"]],
  });
});

// Other tables
$(document).ready(function () {
  $("table.display").DataTable({
    paging: false,
    info: false,
    searching: false,
  });
});
