using System;
using System.Globalization;
using Microsoft.Maui.Controls;

namespace MyGameCatalog.Converters
{
    public class NullOrEmptyToBoolConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            bool result;

            if (value == null)
            {
                result = false;
            }
            else if (value is string str)
            {
                result = !string.IsNullOrWhiteSpace(str);
            }
            else
            {
                result = !string.IsNullOrWhiteSpace(value.ToString());
            }

            if (parameter is string param && param.Equals("invert", StringComparison.OrdinalIgnoreCase))
            {
                result = !result;
            }

            return result;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is bool boolValue)
            {
                if (parameter is string param && param.Equals("invert", StringComparison.OrdinalIgnoreCase))
                {
                    boolValue = !boolValue;
                }

                return boolValue ? " " : null;
            }

            throw new ArgumentException("Value must be a boolean", nameof(value));
        }
    }
}
