using Microsoft.Maui.Controls;
using MyGameCatalog.ViewModels;
using System;

namespace MyGameCatalog.Views
{
    public partial class MainPage : ContentPage
    {
        private readonly MainViewModel _viewModel;

        public MainPage(MainViewModel viewModel)
        {
            InitializeComponent();
            _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
            BindingContext = _viewModel;

            // Subscribe to navigation events
            Appearing += OnPageAppearing;
            Disappearing += OnPageDisappearing;
        }

        private async void OnPageAppearing(object sender, EventArgs e)
        {
            try
            {
                await _viewModel.RefreshCollectionAsync();
            }
            catch (Exception ex)
            {
                await DisplayAlert("Error", "Failed to refresh collection", "OK");
                System.Diagnostics.Debug.WriteLine($"Refresh error: {ex}");
            }
        }

        private void OnPageDisappearing(object sender, EventArgs e)
        {
            // Cleanup if needed
        }

        private async void OnAddGameClicked(object sender, EventArgs e)
        {
            try
            {
                var addGamePage = (Page)App.Current.Services.GetService(typeof(Views.AddGamePage));
                if (addGamePage != null)
                {
                    await Navigation.PushAsync(addGamePage);
                }
                else
                {
                    await DisplayAlert("Error", "Failed to navigate to Add Game page", "OK");
                }
            }
            catch (Exception ex)
            {
                await DisplayAlert("Error", "An error occurred while navigating", "OK");
                System.Diagnostics.Debug.WriteLine($"Navigation error: {ex}");
            }
        }

        protected override void OnDisappearing()
        {
            base.OnDisappearing();
            // Unsubscribe from events
            Appearing -= OnPageAppearing;
            Disappearing -= OnPageDisappearing;
        }
    }
}