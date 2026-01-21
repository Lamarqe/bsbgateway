_DELAY = 500; // ms
function load_all() {
    $('.fieldwidget').each(function(n, elem){
        // set timer to load each field after progressive delay.
        setTimeout(
            function() {
                var disp_id = $(elem).attr('id').replace('fieldwidget-', '');
                $(elem).load('field-'+disp_id+'.widget');
            },
            n*_DELAY
        );
    });
}
function submit_field_null(elem) {
    return submit_field(elem, { set_null:1});
}

function submit_field_Enum(elem) {
    return submit_field(
        elem,
        { value:$(elem).children('select[name="value"]').val() }
    );
}

function submit_field_anydate(elem) {
    return submit_field(
        elem,
        { 
            year:$(elem).children('input[name="year"]').val(),
            month:$(elem).children('input[name="month"]').val(),
            day:$(elem).children('input[name="day"]').val(),
            hour:$(elem).children('input[name="hour"]').val(),   
            minute:$(elem).children('input[name="minute"]').val(),
            second:$(elem).children('input[name="second"]').val()
        }
    );
}

submit_field_Datetime = submit_field_anydate;
submit_field_DayMonth = submit_field_anydate;
submit_field_Time = submit_field_anydate;
submit_field_HourMinutes = submit_field_anydate;

function submit_field_Vals(elem) {
    return submit_field(
        elem,
        { value:$(elem).children('input[name="value"]').val() }
    );
}

submit_field_TimeProgram = submit_field_Vals;
submit_field_String = submit_field_Vals;

function submit_field(elem, data) {
    var url = $(elem).attr('action');
    var id = url.replace('field-', '');
    $.ajax(url, {
        type: 'POST',
        data: data,
        dataType: 'text',
        error: function (response, textStatus, errorThrown) {
            $('#fieldsetresult-'+id).text(textStatus+' '+errorThrown + ' ' + response.responseText).addClass('error');
        },
        success: function (result) {
            $('#fieldsetresult-'+id).text(result).toggleClass('error', (result!='OK'));
            if (result=='OK') {
                $('#fieldwidget-'+id).load('field-'+id+'.widget');
            }
        }
    });
    return false;
}