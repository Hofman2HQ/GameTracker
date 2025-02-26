using Microsoft.Maui.Controls;
using MyGameCatalog.ViewModels;

namespace MyGameCatalog.Views
{
    public partial class LoginPage : ContentPage
    {
        public LoginPage(LoginViewModel viewModel)
        {
            InitializeComponent();
            BindingContext = viewModel;
        }
    }
}