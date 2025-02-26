using Microsoft.Maui.Controls;
using MyGameCatalog.ViewModels;

namespace MyGameCatalog.Views
{
    public partial class MainPage : ContentPage
    {
        public MainPage(MainViewModel viewModel)
        {
            InitializeComponent();
            BindingContext = viewModel;
        }

        private async void OnAddGameClicked(object sender, EventArgs e)
        {
            // Navigate to AddGamePage (resolved from DI)
            await Navigation.PushAsync((Page)App.Current.Services.GetService(typeof(Views.AddGamePage)));
        }
    }
}