using System;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;

namespace MyGameCatalog.Services
{
    public class ErrorHandlingService
    {
        public static async Task HandleErrorAsync(Exception ex, string title = "Error", string operation = null)
        {
            System.Diagnostics.Debug.WriteLine($"Error during {operation}: {ex}");

            var message = ex switch
            {
                ApplicationException appEx => appEx.Message,
                TaskCanceledException => "The operation was cancelled.",
                TimeoutException => "The operation timed out. Please try again.",
                _ => "An unexpected error occurred. Please try again."
            };

            await Application.Current.MainPage.DisplayAlert(
                title,
                message,
                "OK");
        }

        public static async Task<bool> HandleErrorWithRetryAsync(Exception ex, string title = "Error", string operation = null)
        {
            System.Diagnostics.Debug.WriteLine($"Error during {operation}: {ex}");

            var message = ex switch
            {
                ApplicationException appEx => appEx.Message,
                TaskCanceledException => "The operation was cancelled.",
                TimeoutException => "The operation timed out.",
                _ => "An unexpected error occurred."
            };

            return await Application.Current.MainPage.DisplayAlert(
                title,
                $"{message}\nWould you like to try again?",
                "Retry",
                "Cancel");
        }
    }
}
