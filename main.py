# from alor_api_test import AlorApiTest
from DashBoard_volatility import AlorApiTest
from option_app import OptionApp

def main():
    # alor_api_test = AlorApiTest()
    # alor_api_test.run()
    DashBoard_volatility = AlorApiTest()
    # DashBoard_volatility.run_server()
    DashBoard_volatility.run()
    # option_app = OptionApp()
    # option_app.start()

if __name__ == '__main__':
    main()
