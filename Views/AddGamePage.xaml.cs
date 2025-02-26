using Microsoft.Maui.Controls;
using MyGameCatalog.ViewModels;

namespace MyGameCatalog.Views
{
    public partial class AddGamePage : ContentPage
    {
        public AddGamePage(AddGameViewModel viewModel)
        {
            InitializeComponent();
            BindingContext = viewModel;
        }
    }
}