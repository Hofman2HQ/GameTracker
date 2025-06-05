using System;
using System.Globalization;
using Microsoft.Maui.Controls;

namespace MyGameCatalog.Converters
{
    public class NullToBoolConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (parameter is string param && param.Equals("invert", StringComparison.OrdinalIgnoreCase))
            {
                return value == null;
            }

            return value != null;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is bool boolValue)
            {
                if (parameter is string param && param.Equals("invert", StringComparison.OrdinalIgnoreCase))
                {
                    return boolValue ? null : new object();
                }

                return boolValue ? new object() : null;
            }

            throw new ArgumentException("Value must be a boolean", nameof(value));
        }
    }
}