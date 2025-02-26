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
            // Start with the LoginPage (resolved from DI)
            MainPage = new NavigationPage((Page)Current.Services.GetService(typeof(LoginPage)));
        }
    }
}