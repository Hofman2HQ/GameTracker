using Microsoft.Maui;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Controls.Xaml;
using MyGameCatalog.Services.Interfaces;
using MyGameCatalog.Views;

[assembly: XamlCompilation(XamlCompilationOptions.Compile)]
namespace MyGameCatalog
{
    public partial class App : Application
    {
        public App()
        {
            InitializeComponent();

            MainPage = new AppShell();
        }

        protected override Window CreateWindow(IActivationState activationState)
        {
            var window = base.CreateWindow(activationState);

            if (window != null)
            {
                window.Title = "Game Catalog";
                window.Width = 1200;
                window.Height = 800;
                window.MinimumWidth = 800;
                window.MinimumHeight = 600;
            }

            return window;
        }
    }
}