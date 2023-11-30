// This file contains plugin code from the datatables plugin and should 
// not be modified: https://datatables.net/plug-ins/sorting/natural#Browser

// Deeplink
/*!
   Copyright 2017 SpryMedia Ltd.

 License      MIT - http://datatables.net/license/mit

 This feature plug-in for DataTables provides a function which will
 take DataTables options from the browser's URL search string and
 return an object that can be used to construct a DataTable. This
 allows deep linking to be easily implemented with DataTables - for
 example a URL might be `myTable?displayStart=10` which will
 automatically cause the second page of the DataTable to be displayed.

 This plug-in works on a whitelist basis - you must specify which
 [initialisation parameters](//datatables.net/reference/option) you
 want the URL search string to specify. Any parameter given in the
 URL which is not listed will be ignored (e.g. you are unlikely to
 want to let the URL search string specify the `ajax` option).

 This specification is done by passing an array of property names
 to the `$.fn.dataTable.ext.deepLink` function. If you do which to
 allow _every_ parameter (I wouldn't recommend it) you can use `all`
 instead of an array.

 @example
   // Allow a display start point and search string to be specified
   $('#myTable').DataTable(
     $.fn.dataTable.ext.deepLink( [ 'displayStart', 'search.search' ] )
   );

 @example
   // As above, but with a default search
   var options = $.fn.dataTable.ext.deepLink(['displayStart', 'search.search']);

   $('#myTable').DataTable(
     $.extend( true, {
       search: { search: 'Initial search value' }
     }, options )
   );
 Deep linking options parsing support for DataTables
 2017 SpryMedia Ltd - datatables.net/license
*/
(function(l,m,b,n){var h=b.fn.dataTable.ext.internal._fnSetObjectDataFn;b.fn.dataTable.ext.deepLink=function(e){for(var f=location.search.replace(/^\?/,"").split("&"),g={},c=0,k=f.length;c<k;c++){var a=f[c].split("="),d=decodeURIComponent(a[0]);a=decodeURIComponent(a[1]);if("true"===a)a=!0;else if("false"===a)a=!1;else if(!a.match(/[^\d]/)&&"search.search"!==d)a*=1;else if(0===a.indexOf("{")||0===a.indexOf("["))try{a=b.parseJSON(a)}catch(p){}"all"!==e&&-1===b.inArray(d,e)||h(d)(g,a)}return g}})(window,
    document,jQuery);

// Natural Sort
/**
 * Data can often be a complicated mix of numbers and letters (file names
 * are a common example) and sorting them in a natural manner is quite a
 * difficult problem.
 * 
 * Fortunately a deal of work has already been done in this area by other
 * authors - the following plug-in uses the [naturalSort() function by Jim
 * Palmer](http://www.overset.com/2008/09/01/javascript-natural-sort-algorithm-with-unicode-support) to provide natural sorting in DataTables.
 *
 *  @name Natural sorting
 *  @summary Sort data with a mix of numbers and letters _naturally_.
 *  @author [Jim Palmer](http://www.overset.com/2008/09/01/javascript-natural-sort-algorithm-with-unicode-support)
 *  @author [Michael Buehler] (https://github.com/AnimusMachina)
 *
 *  @example
 *    $('#example').dataTable( {
 *       columnDefs: [
 *         { type: 'natural', targets: 0 }
 *       ]
 *    } );
 *
 *    Html can be stripped from sorting by using 'natural-nohtml' such as
 *
 *    $('#example').dataTable( {
 *       columnDefs: [
 *    	   { type: 'natural-nohtml', targets: 0 }
 *       ]
 *    } );
 *
 */

 (function() {

    /*
     * Natural Sort algorithm for Javascript - Version 0.7 - Released under MIT license
     * Author: Jim Palmer (based on chunking idea from Dave Koelle)
     * Contributors: Mike Grier (mgrier.com), Clint Priest, Kyle Adams, guillermo
     * See: http://js-naturalsort.googlecode.com/svn/trunk/naturalSort.js
     */
    function naturalSort (a, b, html) {
        var re = /(^-?[0-9]+(\.?[0-9]*)[df]?e?[0-9]?%?$|^0x[0-9a-f]+$|[0-9]+)/gi,
            sre = /(^[ ]*|[ ]*$)/g,
            dre = /(^([\w ]+,?[\w ]+)?[\w ]+,?[\w ]+\d+:\d+(:\d+)?[\w ]?|^\d{1,4}[\/\-]\d{1,4}[\/\-]\d{1,4}|^\w+, \w+ \d+, \d{4})/,
            hre = /^0x[0-9a-f]+$/i,
            ore = /^0/,
            htmre = /(<([^>]+)>)/ig,
            // convert all to strings and trim()
            x = a.toString().replace(sre, '') || '',
            y = b.toString().replace(sre, '') || '';
            // remove html from strings if desired
            if (!html) {
                x = x.replace(htmre, '');
                y = y.replace(htmre, '');
            }
            // chunk/tokenize
        var	xN = x.replace(re, '\0$1\0').replace(/\0$/,'').replace(/^\0/,'').split('\0'),
            yN = y.replace(re, '\0$1\0').replace(/\0$/,'').replace(/^\0/,'').split('\0'),
            // numeric, hex or date detection
            xD = parseInt(x.match(hre), 10) || (xN.length !== 1 && x.match(dre) && Date.parse(x)),
            yD = parseInt(y.match(hre), 10) || xD && y.match(dre) && Date.parse(y) || null;
    
        // first try and sort Hex codes or Dates
        if (yD) {
            if ( xD < yD ) {
                return -1;
            }
            else if ( xD > yD )	{
                return 1;
            }
        }
    
        // natural sorting through split numeric strings and default strings
        for(var cLoc=0, numS=Math.max(xN.length, yN.length); cLoc < numS; cLoc++) {
            // find floats not starting with '0', string or 0 if not defined (Clint Priest)
            var oFxNcL = !(xN[cLoc] || '').match(ore) && parseFloat(xN[cLoc], 10) || xN[cLoc] || 0;
            var oFyNcL = !(yN[cLoc] || '').match(ore) && parseFloat(yN[cLoc], 10) || yN[cLoc] || 0;
            // handle numeric vs string comparison - number < string - (Kyle Adams)
            if (isNaN(oFxNcL) !== isNaN(oFyNcL)) {
                return (isNaN(oFxNcL)) ? 1 : -1;
            }
            // rely on string comparison if different types - i.e. '02' < 2 != '02' < '2'
            else if (typeof oFxNcL !== typeof oFyNcL) {
                oFxNcL += '';
                oFyNcL += '';
            }
            if (oFxNcL < oFyNcL) {
                return -1;
            }
            if (oFxNcL > oFyNcL) {
                return 1;
            }
        }
        return 0;
    }
    
    jQuery.extend( jQuery.fn.dataTableExt.oSort, {
        "natural-asc": function ( a, b ) {
            return naturalSort(a,b,true);
        },
    
        "natural-desc": function ( a, b ) {
            return naturalSort(a,b,true) * -1;
        },
    
        "natural-nohtml-asc": function( a, b ) {
            return naturalSort(a,b,false);
        },
    
        "natural-nohtml-desc": function( a, b ) {
            return naturalSort(a,b,false) * -1;
        },
    
        "natural-ci-asc": function( a, b ) {
            a = a.toString().toLowerCase();
            b = b.toString().toLowerCase();
    
            return naturalSort(a,b,true);
        },
    
        "natural-ci-desc": function( a, b ) {
            a = a.toString().toLowerCase();
            b = b.toString().toLowerCase();
    
            return naturalSort(a,b,true) * -1;
        }
    } );
    
    }());
    