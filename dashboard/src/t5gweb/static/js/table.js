// Insert Bugzilla Info and Comments into Child Rows
function format(data) {
  let result = "<div class='card p-3'>";
  if (data.group_name != null) {
    result += "<h3>Case Group: " + data.group_name + "</h3>";
  }
  if (data.bugzilla != null) {
    result +=
      '<h3>Bugzillas:</h3><table class="table table-bordered table-hover table-responsive w-100"><thead><tr><th>#</th><th>Summary</th><th>Severity</th><th>Target Release</th><th>Assignee</th><th>QA Contact</th><th>Last Updated</th><th>Status</th></tr></thead><tbody>';
    for (let bug = 0; bug < data.bugzilla.length; bug++) {
      result +=
        '<tr><td><a href="' +
        data.bugzilla[bug].bugzillaLink +
        '" target="_blank">' +
        data.bugzilla[bug].bugzillaNumber +
        "</a></td><td>" +
        data.bugzilla[bug].summary +
        "</td><td>" +
        data.bugzilla[bug].severity +
        "</td><td>" +
        data.bugzilla[bug].target_release[0] +
        "</td><td>" +
        data.bugzilla[bug].assignee +
        "</td><td>" +
        data.bugzilla[bug].qa_contact +
        "</td><td>" +
        data.bugzilla[bug].last_change_time +
        "</td><td>" +
        data.bugzilla[bug].status +
        "</td></tr>";
    }
    result += "</tbody></table>";
  }
  if (data.issues != null) {
    result +=
      '<h3>JIRA Issues:</h3><table class="table table-bordered table-hover table-responsive w-100"><thead><tr><th>#</th><th>Summary</th><th>Priority</th><th>Severity</th><th>Telco Priority</th><th>Target Release</th><th>Assignee</th><th>QA Contact</th><th>Last Updated</th><th>Status</th></tr></thead><tbody>';
    for (let issue = 0; issue < data.issues.length; issue++) {
      const telcoPriority =
        data.issues[issue].private_keywords != null
          ? data.issues[issue].private_keywords.find((str) =>
              str.includes("Priority"),
            )
          : null;
      const priorityNum = telcoPriority
        ? telcoPriority.charAt(telcoPriority.length - 1)
        : 0;
      result +=
        '<tr><td><a href="' +
        data.issues[issue].url +
        '" target="_blank">' +
        data.issues[issue].id +
        "</a></td><td>" +
        data.issues[issue].title +
        "</td><td>" +
        (data.issues[issue].priority != null
          ? data.issues[issue].priority
          : "---") +
        "</td><td>" +
        (data.issues[issue].jira_severity != null
          ? data.issues[issue].jira_severity
          : "---") +
        `</td><td class="telco-priority-${priorityNum}">` +
        (data.issues[issue].private_keywords != null
          ? data.issues[issue].private_keywords.find((str) =>
              str.includes("Priority"),
            ) || "---"
          : "---") +
        "</td><td>" +
        (data.issues[issue].fix_versions != null
          ? data.issues[issue].fix_versions
          : "---") +
        "</td><td>" +
        (data.issues[issue].assignee != null
          ? data.issues[issue].assignee
          : "---") +
        "</td><td>" +
        (data.issues[issue].qa_contact != null
          ? data.issues[issue].qa_contact
          : "---") +
        "</td><td>" +
        data.issues[issue].updated +
        "</td><td>" +
        data.issues[issue].status +
        "</td></tr>";
    }
    result += "</tbody></table>";
  }
  result += "<h3>Comments:</h3><ul>";
  for (let comment = data.comments.length - 1; comment >= 0; comment--) {
    result +=
      '<li class="text-break"><span class="fw-bold fst-italic">' +
      data.comments[comment][1].substring(0, 10) +
      "</span> - " +
      data.comments[comment][0] +
      "</li>";
  }
  result += "</ul>";
  return result + "</div>";
}

// Initialize DataTable
$(document).ready(function () {
  // Define configuration options for DataTable:

  // Deeplinking: https://datatables.net/blog/2017-07-24#Usage
  let deeplinkList = [
    "search.search",
    "order",
    "displayStart",
    "searchPanes.preSelect",
  ];
  let searchOptions = $.fn.dataTable.ext.deepLink(deeplinkList);

  // General Options for DataTable
  let options = {
    pageLength: 50,
    scrollX: true,
    scrollY: "75vh",
    order: [
      [2, "desc"],
      [3, "desc"],
      [4, "desc"],
    ],
    dom: "<'row'<'col-sm-12 col-md-6'l><'col-sm-12 col-md-6'f>><'row'<'col-sm-12 col-md-5'i><'col-sm-12 col-md-7'p>><'row'<'col-sm-12'tr>><'row'<'col-sm-12 col-md-5'i><'col-sm-12 col-md-7'p>>",
    lengthMenu: [
      [10, 25, 50, -1],
      [10, 25, 50, "All"],
    ],

    // searchPanes: https://datatables.net/extensions/searchpanes/
    searchPanes: {
      order: [
        "Severity",
        "On Prio-list?",
        "Product",
        "Escalated?",
        "Account",
        "Internal Status",
      ],
      columns: [2, 3, 6, 7, 9],
      initCollapsed: true,

      // Define Custom Search Pane
      panes: [
        {
          name: "Escalated?",
          header: "Escalated?",
          options: [
            {
              label: "Cases on Prio-list or Crit Sit",
              value: function (rowData, rowIdx) {
                return (
                  rowData[3].includes("Yes") ||
                  rowData[4] === "Yes"
                );
              },
            },
            {
              label: "Cases on Daily Telco List",
              value: function (rowData, rowIdx) {
                return rowData[15] === "True";
              },
            },
          ],
        },
      ],
    },

    // When table is loaded, remove "Loading Table..." message and display table
    initComplete: function (settings, json) {
      $("div.loading").remove();
      $(".case-table").show();
      $($.fn.dataTable.tables(true)).DataTable().columns.adjust();
    },
    columnDefs: [
      { type: "html", targets: 2 },

      // Make sure filters are always shown
      {
        searchPanes: {
          show: true,
        },
        targets: [2, 7, 9],
      },

      // Include cards marked as 'Potentially' in 'No' category
      {
        searchPanes: {
          show: true,
          options: [
            {
              label: "No",
              value: function (rowData, rowIdx) {
                return rowData[3] == "No" || rowData[3] == "Potentially";
              },
            },
            {
              label: "Yes",
              value: function (rowData, rowIdx) {
                return rowData[3].includes("Yes");
              },
            },
            {
              label: "Potentially",
              value: function (rowData, rowIdx) {
                return rowData[3] === "Potentially";
              },
            },
          ],
        },
        targets: [3],
      },
      // Hide Daily Telco List Column
      {
        targets: [15],
        visible: false,
      },
    ],
  };

  // Initialize Table w/ options defined above
  let table = $("#data").DataTable($.extend(true, options, searchOptions));
  table.searchPanes.container().prependTo(table.table().container());
  table.searchPanes.resizePanes();

  // Add event listener for opening and closing details
  $("#data").on("click", "td.dt-control", function () {
    let tr = $(this).closest("tr");
    let row = table.row(tr);

    if (row.child.isShown()) {
      // This row is already open - close it
      row.child.hide();
      tr.removeClass("shown");
    } else {
      // Open this row
      row.child(format(tr.data("child-data"))).show();
      tr.addClass("shown");
    }
  });

  // Expand and Collapse all Rows - Adapted from https://www.gyrocode.com/articles/jquery-datatables-how-to-expand-collapse-all-child-rows/
  $("#expand-button").on("click", function () {
    table.rows().every(function () {
      if (!this.child.isShown()) {
        this.child(format($(this.node()).data("child-data"))).show();
        $(this.node()).addClass("shown");
      }
    });
  });
  $("#collapse-button").on("click", function () {
    table.rows().every(function () {
      if (this.child.isShown()) {
        this.child.hide();
        $(this.node()).removeClass("shown");
      }
    });
  });

  /**
   * updateOrder() retrieves the current column order settings
   * and updates the URL to reflect these settings
   */
  function updateOrder() {
    let order = JSON.stringify(table.order());
    if (order.length > 0) {
      if (query.includes("order=")) {
        // Update order section of query in place
        query = query.replace(/order=.[^&]*/i, "order=" + order);
      } else {
        if (query.length > 1) {
          query = query + "&";
        }
        query = query + "order=" + order;
      }
    } else {
      if (query.includes("order")) {
        // Remove order section from query
        query = query.replace(/&?order=.[^&]*/i, "");
      }
    }
    history.replaceState(null, null, query);
  }

  /**
   * updateSearch() retrieves the current search settings
   * and updates the URL to reflect these settings
   */
  function updateSearch() {
    let search = table.search();
    if (search.length > 0) {
      if (query.includes("search.search=")) {
        // Update search section of query in place
        query = query.replace(
          /search.search=.[^&]*/i,
          "search.search=" + search,
        );
      } else {
        if (query.length > 1) {
          query = query + "&";
        }
        query = query + "search.search=" + search;
      }
    } else {
      if (query.includes("search.search")) {
        // Remove search section from query
        query = query.replace(/&?search.search=.[^&]*/i, "");
      }
    }
    history.replaceState(null, null, query);
  }

  /**
   * updatePanes() retrieves the current search panes settings
   * and updates the URL to reflect these settings
   */
  function updatePanes() {
    let panes = [];
    setTimeout(function () {
      // Retrieve active filters
      $.each($("div.dtsp-searchPane"), function (i, col) {
        let colName = $(col).find("input").attr("placeholder");
        let colIndex = table.column(":contains(" + colName + ")").index();
        if (colIndex == undefined) {
          // If more custom search panes are added, this section needs to be changed
          colIndex = extraCol + 1;
        }
        let column = { column: colIndex, rows: [] };
        let rows = [];
        $.each($("tr.selected", col), function (j, row) {
          rows.push($("span:eq(0)", row).text());
        });
        if (rows.length != 0) {
          column.rows = rows;
          panes.push(column);
        }
      });

      // Update URL with active filters
      if (panes.length > 0) {
        if (query.includes("searchPanes.preSelect")) {
          // Update search panes section of query in place
          query = query.replace(
            /searchPanes.preSelect=.[^&]*/i,
            "searchPanes.preSelect=" + JSON.stringify(panes),
          );
        } else {
          if (query.length > 1) {
            query = query + "&";
          }
          query = query + "searchPanes.preSelect=" + JSON.stringify(panes);
        }
      } else {
        if (query.includes("searchPanes.preSelect")) {
          // Remove search panes section from query
          query = query.replace(/&?searchPanes.preSelect=.[^&]*/i, "");
        }
      }
      history.replaceState(null, null, query);
    }, 1);
  }

  // Make sure previous URL settings are not overwritten
  let url = window.location.href;
  let query = "";
  if (url.includes("?")) {
    let deeplink = url.slice(url.indexOf("?"));
    if (deeplink.length > 1) {
      query = deeplink;
    }
  } else {
    query = "?";
  }

  let extraCol = table.columns()[0].length - 1;

  /**
   * Update order and search pane settings when datatable is reordered,
   * and update search settings when a search event occurs
   */
  $("#data").on("order.dt", updateOrder);
  $("#data").on("order.dt", updatePanes);
  $("#data").on("search.dt", updateSearch);
});
