/**
 * The following code, along with refresh() and refresh_status() in t5gweb/ui.py
 * was derived from https://blog.miguelgrinberg.com/post/using-celery-with-flask 
 * under the following license:
    
 *   The MIT License (MIT)

 *   Copyright (c) 2014 Miguel Grinberg

 *   Permission is hereby granted, free of charge, to any person obtaining a copy
 *   of this software and associated documentation files (the "Software"), to deal
 *   in the Software without restriction, including without limitation the rights
 *   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 *   copies of the Software, and to permit persons to whom the Software is
 *   furnished to do so, subject to the following conditions:
 *
 *   The above copyright notice and this permission notice shall be included in all
 *   copies or substantial portions of the Software.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 *   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 *   SOFTWARE.
 */

/**
 * On page load, get status of most recent background refresh
 * If refresh is in progress, display progress bar and call updatePercentage()
 * to continuously update it.
 */
$(document).ready(function () {
  $.ajax({
    type: "POST",
    url: "/progress/status",
    success: function (data, status, request) {
      status_url = request.getResponseHeader("Location");
      $.getJSON(status_url, function (data) {
        if (data["state"] == "PROGRESS") {
          $("#progressbar").empty();
          div = $(
            '<div class="text-center text-white">Refresh in progress...</div> <div class="text-white progress"><div class="progress-bar bg-danger" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">0%</div></div>',
          );
          $("#progressbar").append(div);
          updatePercentage(status_url, $("#progressbar"));
        }
      });
    },
    error: function () {
      alert("Unexpected error");
    },
  });
});

/**
 * getBackground() displays the progress bar when the refresh button is clicked
 * and gets progress information from the task. Also calls updatePercentage()
 * to continuously update the progress bar.
 */
function getBackground() {
  $("#progressbar").empty();
  div = $(
    '<div class="text-center text-white">Refresh in progress...</div> <div class="text-white progress"><div class="progress-bar bg-danger" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">0%</div></div>',
  );
  $("#progressbar").append(div);
  $.ajax({
    type: "POST",
    url: "/refresh",
    success: function (data, status, request) {
      status_url = request.getResponseHeader("Location");
      updatePercentage(status_url, $("#progressbar"));
    },
    error: function () {
      alert("Unexpected error");
    },
  });
}

/**
 * updatePercentage() gets the progress of the refresh and updates the progress bar
 * every two seconds. Also displays the final result of the task.
 */
function updatePercentage(status_url, div) {
  $.getJSON(status_url, function (data) {
    percent = parseInt((data["current"] * 100) / data["total"]);
    div
      .find(".progress-bar")
      .css("width", percent + "%")
      .attr("aria-valuenow", percent)
      .text(percent + "%");
    if (!("locked" in data)) {
      if (data["state"] != "PENDING" && data["state"] != "PROGRESS") {
        if ("result" in data) {
          // show result
          $(div).text(data["result"]).css("color", "white");
        } else {
          // something unexpected happened
          $(div)
            .text(data["state"] + ", please try again.")
            .css("color", "white");
        }
      } else {
        // rerun in 2 seconds
        setTimeout(function () {
          updatePercentage(status_url, div);
        }, 2000);
      }
    }
  });
}

/**
 * Start background refresh on button click
 */
$(function () {
  $("#refresh").click(getBackground);
});
